from jose import jwt
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, Response, Form, status, HTTPException, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from typing import Optional, List
from jose import JWTError
import json

from bbdd.response.user_response import UserResponse

from aux_main.aux_main_login import get_current_user_optional, get_current_user, aux_login_post
from aux_main.aux_main_general import (
    aux_mis_analisis, aux_analysis_by_id, aux_filter_analysis_geo,
    aux_dashboard_data, aux_run_aceptacion, aux_read_aceptacion, aux_filter_aceptacion_geo,
    aux_download_aceptacion_txt, aux_download_analysis, aux_generate_keywords,
    get_analyses_for_user, aux_download_analysis_pdf, ejecutar_eliminacion_sana_by_slug,
    aux_get_grafo, aux_get_visual_semantico, aux_get_lexico_semantico_v2,
)
from aux_main.classes_main import FilterRequest
from bbdd.database import Base, engine, get_db

from bbdd.models_all import AnalysisTask, TaskStatus, TaskTypeEnum, Analysis, AnalysisStatus, generate_slug
from bbdd.database import SessionLocal
from bbdd.init_db import create_test_users
from aux_main.task_service import TaskService
import asyncio

from generate_report import build_analysis_pdf

import io
import os
import base64
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import func

from pathlib import Path
from logica_FORMAT import calcular_dashboard_base
import csv
import uuid
import traceback

from tasks import ejecutar_analisis_task

from aux_main.llm_utils import require_llm, check_llm_available

from aux_main.aux_root import verificar_metrics_token
from aux_main.aux_data_metrics import start_data_metrics_thread
from seguridad.audit_service import AuditService, EventType, EventResult, get_request_context
##############################################################
#
#   Tipo de Servidor: Servidor sin estado (stateles server) 
#   Las sesiones no se guardan en caché, sino con un token
#   que se verifica contantemente
##############################################################

###################################
#   Estructura del main:
#   1) Todas las librerías arriba
#   2) Cada endpoint hace:
#       a) Validación de autenticación/rol
#       b) Delegación a aux_main para la lógica real
#       c) Cosas muy básicas + redirección
###################################

templates = Jinja2Templates(directory="templates")
Base.metadata.create_all(bind=engine)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
start_data_metrics_thread()

METRICS_PATH = os.getenv("METRICS_PATH", "/_metrics_09_81")

@app.get(METRICS_PATH, include_in_schema=False)
def metrics(_: bool = Depends(verificar_metrics_token)):
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

'''
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
Instrumentator().instrument(app)

#======================================================================================================
# function -> metrics
#   Objetivo:   Se encarga de devolver las métricas que reocge prometheus.
#               Este endpoint debería ser oculto a cualquier usuario.+
#               Solo debería ser ejeuctado por el ADMINISTRADOR del panel.
#               Su nombre "_metrics_" es para indicarnos que es el endpoint de las métricas.
#               Los carácteres que le prosiguen es para asegurar de que no se haya introducido
#               de manera casi aletoria.
#   Retorno:    Si todo es correcto, devuelve el usuario con la estructura UserResponse; sino un error.
#=======================================================================================================

@app.get("/_metrics_09_81", include_in_schema=False)
def metrics(user=Depends(verificar_root)):
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
'''

########################################################################
#  Helpers de autenticación
########################################################################

#======================================================================================================
# function -> require_roles
#   Objetivo:   Se encarga de verificar que un usuario tenga el rol
#               necesario que se especifica en el End-Point para ejecutarlo.
#               Además ejecuta "get_current_user", el cual se encarga constantemente de
#               verificar que el usuario existe y es válido.
#   Retorno:    Si todo es correcto, devuelve el usuario con la estructura UserResponse; sino un error.
#=======================================================================================================
def require_roles(allowed_roles: List[str]):
    def dependency(
        current_user: UserResponse = Depends(get_current_user),
        db: Session = Depends(get_db),
        ctx: dict = Depends(get_request_context),
    ):
        if current_user.role not in allowed_roles:
            AuditService.user_action(
                db, EventType.ACCESS_DENIED, result=EventResult.WARNING,
                user_id=current_user.id, username=current_user.username,
                message=(
                    f"@{current_user.username} (rol '{current_user.role}') intentó acceder "
                    f"a una ruta que requiere uno de estos roles: {allowed_roles}"
                ),
                details={"required_roles": allowed_roles, "actual_role": current_user.role},
                ctx=ctx,
            )
            raise HTTPException(403, "No tienes permisos suficientes")
        return current_user
    return Depends(dependency)

#======================================================================================================
# function -> llm_status
#   Objetivo:   Se encarga de verificar constantemente de si el modelo LLM está levantado o no.
#   Retorno:    True: si el modelo está levantado. False: en caso contrario.
#=======================================================================================================
@app.get("/api/llm/status")
def llm_status(
    current_user: UserResponse = Depends(get_current_user)
):
    return {
        "available": check_llm_available()
    }
    
########################################################################
#  Rutas de navegación base
########################################################################

#======================================================================================================
# function -> root
#   Objetivo:   Es la base de la url "/". Se encarga de redireccionar a "/login" si no está logueado.
#               En caso de estar logueado redirecciona a "/analisis"
#   Retorno:    Redirecciona a la FUNCIÓN correspondiente
#=======================================================================================================
@app.get("/")
def root(current_user: UserResponse | None = Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/analisis", status_code=302)

#======================================================================================================
# function -> login
#   Objetivo:   Es la url "/login". Si el usuario no está logueado, devuelve el "HTML" para loguearse.
#               En caso de estar logueado redirecciona a "/analisis"
#   Retorno:    Devuelve el HTML de logueo si está logueado o redirecciona a la FUNCIÓN "/analisis"
#=======================================================================================================
@app.get("/login")
def login(request: Request, current_user: UserResponse | None = Depends(get_current_user_optional)):
    if not current_user:
        return templates.TemplateResponse("login.html", {"request": request, "error": None})
    return RedirectResponse(url="/analisis", status_code=302)

#======================================================================================================
# function -> login_post
#   Objetivo:   Recoge el POST de login del usuario (usuario y contraseña).
#               Si el usuario existe y es válido, crea un token para él, el cual se almacena en las
#               las cookies. Sino, devuelve el HTML de logueo.
#               (En el frontend, en caso de éxito, recarga la página. Entonces, como ya tiene las
#               cookies de sesión (ya está logueado), se redirecciona a "/analisis")
#   Retorno:    Devuelve el HTML de login en caso de mal logueo. O el mensaje JSON para el frontend 
#               de éxito de logueo.
#=======================================================================================================
@app.post("/login")
def login_post(request: Request, response: Response, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db), log_ctx: dict = Depends(get_request_context)):
    token_user = aux_login_post(username, password, log_ctx)

    if not token_user:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Usuario o contraseña incorrectos"})

    response.set_cookie(key="access_token", value=token_user, httponly=True, samesite="lax", secure=False)
    return {"message": "Login correcto"}

#======================================================================================================
# function -> logut
#   Objetivo:   Elimina las cookies de sesión y redicciona a la FUNCIÓN de login
#   Retorno:    Devuelve la redirección de la FUNCIÓN de "/login"
#=======================================================================================================
@app.post("/logout")
def logout(
    request: Request,
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context),
    current_user: UserResponse | None = Depends(get_current_user_optional),
):
    if current_user:
        AuditService.user_action(
            db, EventType.LOGOUT,
            user_id=current_user.id, username=current_user.username,
            message=f"@{current_user.username} cerró sesión",
            ctx=ctx,
        )
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="access_token")
    return response


########################################################################
#  Análisis — ejecución y tareas
########################################################################

#======================================================================================================
# function -> ejecutar_analisis
#   Objetivo:   Ejecuta el ANÁLISIS PRINCIPAL de "index.html" con los parámetros del usuario.
#   Retorno:    Devuelve la redirección de la FUNCIÓN de "/login"
#=======================================================================================================
@app.post("/ejecutar-analisis")
async def ejecutar_analisis(
    request: Request,
    current_user: UserResponse = require_roles(["analista", "admin"]),
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context)
):
    data = await request.json()
    data["username"] = current_user.username

    #Si el modelo no está levanado, debería lanzar un error. 
    # En el frontend ya se bloquea el botón en caso de que esto pase. No debería llegar aquí si pasara
    require_llm()
    
    #Miramos si el nombre del proyecto existe. Si es así, error, no debería pasar
    # Desde el frontend se impide esto. No debería pasar aquí, pero se vuelve a
    # verificar que sea así.
    existing = db.query(Analysis).filter(
        Analysis.user_id == current_user.id,
        func.lower(Analysis.project_name) == data.get("project_name").lower()
    ).first()

    if existing:
        #Si se ha producido un error, es porque en la BBDD del usuario ya existe
        # un proyecto con el mismo nombre (la comprobación se normaliza a minusculas)
        # Es decir:
        # "Proyecto Bueno" = "proyecto BUENO" -> "proyecto bueno" = "proyecto bueno"
        # Se hace así para que el enpoint se distinga mejor ".../analisis/proyecto_bueno"
        raise HTTPException(
            status_code=400,
            detail="Ya existe un proyecto con ese nombre"
        )

    try:
        slug_name = generate_slug(db, data["project_name"], current_user.username)

        analysis_record = {
            "id":               f'{data.get("username")}-{slug_name}',
            "project_name":     data.get("project_name"),
            "tema":             data.get("tema") or data.get("asistente"),
            "desc_tema":        data.get("desc_tema", ""),
            "username":         data.get("username"),
            "output_folder":    f'datos/{current_user.username}/{data.get("project_name")}',
            "sources":          data.get("sources", []),
            "keywords":         data.get("keywords", []),
            "languages":        data.get("languages", []),
            "population_scope": data.get("population"),
            "tipo_tema":        data.get("tipo_tema", "GLOBAL"),
            "start_date":       data.get("start_date"),
            "end_date":         data.get("end_date"),
            "status":           "completed",
            "created_at":       datetime.now().isoformat()
        }
        analysis = Analysis(
            user_id=current_user.id,
            project_name=data["project_name"],
            slug=slug_name,
            status=AnalysisStatus.DRAFT,
            output_folder=f'datos/{current_user.username}/{data["project_name"]}',
            analysis_config=analysis_record,
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        
        id_project = {"user": slug_name, "bbdd": analysis.id}

        task = TaskService.create_task(
            db=db,
            analysis_id=id_project["bbdd"],
            user_id=None,
            task_type=TaskTypeEnum.SCRAPING,
            input_config={"action": "ejecutar_analisis", "data": data},
            priority=3,
        )

        analysis.status = AnalysisStatus.ACTIVE
        db.commit()

        celery_task = ejecutar_analisis_task.delay(data=data, analysis_id=analysis.id, task_id=task.id)
        task.celery_task_id = celery_task.id
        db.commit()
        db.refresh(task)

        TaskService.update_status(
            db=db,
            task_id=task.id,
            status=TaskStatus.QUEUED,
            message="Tarea encolada en Celery",
            current_step=f"Esperando worker. Celery task_id: {celery_task.id}",
        )

        AuditService.user_action(
            db, EventType.PROJECT_CREATED,
            user_id=current_user.id, username=current_user.username,
            message=f"@{current_user.username} creó el proyecto '{data['project_name']}'",
            target_type="analysis", target_id=analysis.id, target_label=data["project_name"],
            ctx=ctx,
        )
        
        return {"task_id": task.id, "analysis_id": analysis.id, "project_slug": slug_name, "status": "queued"}

    except Exception as e:
        print(e)
        db.rollback()
        AuditService.user_action(
            db, EventType.PROJECT_CREATED, result=EventResult.FAILURE,
            user_id=current_user.id, username=current_user.username,
            message=f"Error creando proyecto para @{current_user.username}: {e}",
            target_label=data.get("project_name"),
            details={"error": str(e)},
            ctx=ctx,
        )
        raise HTTPException(status_code=500, detail=str(e))

#======================================================================================================
# function -> generate_keywords
#   Objetivo:   Se encarga de generar keywords consultando al modelo con el tema que introduce el
#               usuario. Además, registra todo esto en la BBDD.
#   Retorno:    Devuelve el JSON con asl keywords, descripción del tema y el tipo de tema generado por
#               el LLM. En caso de error, se registra en la BBDD y devuelve el error.
#=======================================================================================================
@app.post("/generate_keywords")
async def generate_keywords(
    request: Request,
    current_user: UserResponse = require_roles(["analista", "admin"]),
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context)
):
    data = await request.json()
    task = None

    require_llm()
    
    try:
        task = TaskService.create_task(
            db=db,
            analysis_id=None,
            user_id=current_user.id,
            task_type=TaskTypeEnum.GENERATING_KW,
            input_config={"action": "generate_keywords", "data": data},
        )
        TaskService.update_status(db=db, task_id=task.id, status=TaskStatus.RUNNING, message="Generando keywords con LLM...")

        keywords = aux_generate_keywords(data)

        TaskService.update_status(
            db=db, task_id=task.id, status=TaskStatus.COMPLETED,
            message=f"Keywords generadas: {len(keywords)} encontradas",
            progress_percent=100,
            output_summary={"keywords_count": len(keywords), "keywords": keywords},
        )

        AuditService.user_action(
            db, EventType.KEYWORDS_GENERATED,
            user_id=current_user.id, username=current_user.username,
            message=f"@{current_user.username} generó nuevas KEYWORDS",
            target_type="keywords",
            ctx=ctx,
        )
        
        return JSONResponse({
            "success": True,
            "keywords": keywords.get("keywords", []),
            "desc_tema": keywords.get("brief", ""),
            "tipo_tema": keywords.get("tipo_tema", ""),
        })

    except Exception as e:
        print("ERROR EN generate_keywords:", traceback.format_exc())
        if task is not None:
            TaskService.update_status(db=db, task_id=task.id, status=TaskStatus.FAILED, error_message=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/{task_id}/status")
def get_task_status(task_id: int, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db), ctx: dict = Depends(get_request_context),):
    try:
        task = TaskService.get_task(db, task_id)
        if not task:
            raise HTTPException(404, "Tarea no encontrada")

        if task.analysis_id:
            if task.analysis.user_id != current_user.id:
                AuditService.user_action(
                    db, EventType.ACCESS_DENIED, result=EventResult.WARNING,
                    user_id=current_user.id, username=current_user.username,
                    message=f"@{current_user.username} intentó ver el estado de una tarea ajena (#{task_id})",
                    target_type="task", target_id=task_id,
                    ctx=ctx,
                )
                raise HTTPException(403, "No autorizado")
        elif task.user_id:
            if task.user_id != current_user.id:
                AuditService.user_action(
                    db, EventType.ACCESS_DENIED, result=EventResult.WARNING,
                    user_id=current_user.id, username=current_user.username,
                    message=f"@{current_user.username} intentó ver el estado de una tarea ajena (#{task_id})",
                    target_type="task", target_id=task_id,
                    ctx=ctx,
                )
                raise HTTPException(403, "No autorizado")

        return {
            "id": task.id,
            "status": task.status.value,
            "progress": task.progress_percent,
            "current_step": task.current_step,
            "message": task.message,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "error": task.error_message
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


########################################################################
#  SSE — progreso y detener
########################################################################

#======================================================================================================
# function -> stream_progreso
#   Objetivo:   Devuelve el estado de la tarea de "ejecutar_analisis".
#               Formato: progreso, si ha habido una cancelación de la tarea o si ha habido un error
#   Params:     task_id -> es el id indexado en la BBDD de la tarea (0..10...59...)
#   Retorno:    Devuelve el JSON los estados de la tarea
#=======================================================================================================
@app.get("/analisis/{analysis_id}/progreso")
async def stream_progreso(
    analysis_id: int,
    request: Request,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        analysis = db.query(Analysis).filter(
            Analysis.id == analysis_id,
            Analysis.user_id == current_user.id
        ).first()

        if not analysis:
            raise HTTPException(status_code=404, detail="Análisis no encontrado")

        async def event_generator():
            while True:
                db_local = SessionLocal()
                if await request.is_disconnected():
                    db_local.close()
                    break
                try:
                    task = db_local.query(AnalysisTask).filter(
                        AnalysisTask.analysis_id == analysis_id
                    ).order_by(AnalysisTask.created_at.desc()).first()

                    if not task:
                        yield f"data: {json.dumps({'error': True, 'mensaje': 'Sin tareas'})}\n\n"
                        await asyncio.sleep(1)
                        continue

                    payload = {
                        "paso":       task.current_step or task.status,
                        "porcentaje": task.progress_percent or 0,
                        "mensaje":    task.message or "",
                        "cancelled":  task.status == TaskStatus.CANCELLED,
                        "error":      task.status == TaskStatus.FAILED,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                    if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                        break
                finally:
                        db_local.close()

                await asyncio.sleep(1)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

#======================================================================================================
# function -> detener_analisis
#   Objetivo:   Se encarga de detener en análisis basándose en la id de la BBDD del análisis.
#               Para ello verifica si ese id existe y está relacionado con el usuario que la ejecuta.
#   Params:     analysis_id -> es el id indexado en la BBDD de la tarea (0..10...59...)
#   Retorno:    Devuelve el JSON los estados de la tarea
#=======================================================================================================
@app.post("/analisis/{analysis_id}/detener")
async def detener_analisis(
    analysis_id: int,
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context)
):
    try:
        analysis = db.query(Analysis).filter(
            Analysis.id == analysis_id,
            Analysis.user_id == current_user.id
        ).first()

        if not analysis:
            detener_analisis_ajeno = db.query(Analysis.id).filter(Analysis.id == analysis_id).first()
            if detener_analisis_ajeno:
                AuditService.user_action(
                    db, EventType.ACCESS_DENIED, result=EventResult.WARNING,
                    user_id=current_user.id, username=current_user.username,
                    message=f"@{current_user.username} intentó detener un análisis ajeno (#{analysis_id})",
                    target_type="analysis", target_id=analysis_id,
                    ctx=ctx,
                )
            raise HTTPException(status_code=404, detail="Análisis no encontrado")

        task = db.query(AnalysisTask).filter(
            AnalysisTask.analysis_id == analysis_id,
            AnalysisTask.status.in_(["queued", "running"])
        ).order_by(AnalysisTask.created_at.desc()).first()

        if not task:
            return {"status": "no_active_task"}

        task.status = TaskStatus.CANCELLED
        task.message = "Cancelado por el usuario"
        task.finished_at = datetime.now(timezone.utc)
        task.progress_percent = task.progress_percent or 0
        analysis.status = AnalysisStatus.CANCELLED
        
        db.commit()

        try:
            from celery_app import celery_app
            celery_app.control.revoke(task.celery_task_id, terminate=True, signal="SIGKILL")
        except Exception as e:
            print("Celery revoke no aplicado:", e)

        AuditService.user_action(
            db, EventType.PROJECT_STOPPED,
            user_id=current_user.id, username=current_user.username,
            message=f"@{current_user.username} detuvo el análisis '{analysis.project_name}'",
            target_type="analysis", target_id=analysis.id, target_label=analysis.project_name,
            ctx=ctx,
        )
        
        return {"status": "cancelled", "analysis_id": analysis_id, "task_id": task.id}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


########################################################################
#  Dashboard y filtros
########################################################################

#======================================================================================================
# function -> home
#   Objetivo:   En caso de logueo, devuelve el HTML principal del "index.html"
#   Retorno:    Devuelve el HTML de "index.html"
#=======================================================================================================
@app.get("/analisis")
def home(request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    return templates.TemplateResponse("index.html", {"request": request, "resultado": None, "user": current_user})

#======================================================================================================
# function -> view_analysis
#   Objetivo:   Redirecciona a "/analisis/{analysis_id_slug}/dashboard" 
#   Params:     analysis_id_slug -> Es el id del proyecto en formato "slug"
#               (ej: "Proyecto BaLIza v16" -> "proyecto_baliza_v16"). Actúa como ID único del proyecto
#               del usuario.
#   Retorno:    Devuelve la redirección FUNCIÓN de "/analisis/{analysis_id_slug}/dashboard" 
#=======================================================================================================
@app.get("/analisis/{analysis_id_slug}")
def view_analysis(request: Request, analysis_id_slug: str, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    return RedirectResponse(url=f"/analisis/{analysis_id_slug}/dashboard", status_code=302)

#======================================================================================================
# function -> download_analysis
#   Objetivo:   Descarga el análisis del proyecto en formato PDF
#   Params:     analysis_id -> Es el id de la BBDD del proyecto
#   Retorno:    Devuelve el documento PDF 
#=======================================================================================================
@app.get("/analisis/{analysis_id}/download")
async def download_analysis(analysis_id: int, current_user: UserResponse = require_roles(["analista", "admin"]), db: Session = Depends(get_db)):
    return await aux_download_analysis_pdf(analysis_id, current_user)

#======================================================================================================
# function -> get_dashboard_data
#   Objetivo:   Se encarga de devolver el análisis de un proyecto en concreto 
#   Params:     analysis_id_slug -> Es el id del proyecto en formato "slug"
#               (ej: "Proyecto BaLIza v16" -> "proyecto_baliza_v16"). Actúa como ID único del proyecto
#               del usuario.
#   Retorno:    Devuelve el HTML del análisis del proyecto analysis_id_slug
#=======================================================================================================
@app.get("/analisis/{analysis_id_slug}/dashboard")
def get_dashboard_data(request: Request, analysis_id_slug: str, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        return aux_dashboard_data(db, analysis_id_slug, current_user)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

#======================================================================================================
# function -> filter_analysis_geo
#   Objetivo:   Se encarga de hacer un filtro geográfico. Requiere que el LLM esté levantado
#   Params:     analysis_slug -> Es el id del proyecto en formato "slug"
#               (ej: "Proyecto BaLIza v16" -> "proyecto_baliza_v16"). Actúa como ID único del proyecto
#               del usuario.
#   Retorno:    Devuelve un JSON con los resultados
#=======================================================================================================
@app.post("/analisis/{analysis_slug}/filter-geo")
def filter_analysis_geo(request: Request, analysis_slug: str, payload: FilterRequest, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    require_llm()
    return aux_filter_analysis_geo(db, analysis_slug, payload, current_user)


########################################################################
#  Aceptación
########################################################################

#======================================================================================================
# function -> filter_analysis_geo
#   Objetivo:   Se encarga de ejecutar el análisis de aceptación de un proyecto concreto (analysis_slug)
#   Params:     analysis_slug -> Es el id del proyecto en formato "slug"
#               (ej: "Proyecto BaLIza v16" -> "proyecto_baliza_v16"). Actúa como ID único del proyecto
#               del usuario.
#   Retorno:    Devuelve un JSON con los resultados de la aceptación o un error.
#=======================================================================================================
@app.post("/analisis/{analysis_slug}/aceptacion")
async def run_aceptacion(request: Request, analysis_slug: str, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db), ctx: dict = Depends(get_request_context)):
    
    require_llm()
    try:
        result = await aux_run_aceptacion(analysis_slug, current_user)
        analysis = db.query(Analysis).filter(Analysis.slug == analysis_slug, Analysis.user_id == current_user.id).first()
        
        AuditService.user_action(
                    db, EventType.ACEPTACION_GENERATED,
                    user_id=current_user.id, username=current_user.username,
                    message=f"@{current_user.username} generó la ACEPTACION del proyecto '{analysis.project_name}'",
                    target_type="aceptacion", target_id=analysis.id, target_label=analysis.project_name,
                    ctx=ctx,
                )
        return JSONResponse(content=jsonable_encoder(result))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

#======================================================================================================
# function -> filter_analysis_geo
#   Objetivo:   Es lo mismo que /analisis/{analysis_slug}/aceptacion, pero solo lectura desde el principio
#               El objetivo principal es que si ya se cargó el análisis de aceptación, los resultados
#               puedan estar disponibles, aunque el LLM no esté levantado.
#   Params:     analysis_slug -> Es el id del proyecto en formato "slug"
#               (ej: "Proyecto BaLIza v16" -> "proyecto_baliza_v16"). Actúa como ID único del proyecto
#               del usuario.
#   Retorno:    Devuelve un JSON con los resultados de la aceptación o un error.
#=======================================================================================================
@app.post("/analisis/{analysis_slug}/read_aceptacion")
async def run_aceptacion(request: Request, analysis_slug: str, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):

    try:
        result = await aux_read_aceptacion(analysis_slug, current_user)
        return JSONResponse(content=jsonable_encoder(result))
    except Exception as e:
        print(F'FALLO: {e}')
        raise HTTPException(status_code=400, detail=str(e))
    

#======================================================================================================
# function -> filter_aceptacion_geo
#   Objetivo:   Se encarga de hacer un filtro geográfico dentro del análisis de aceptación.
#               Requiere que el LLM esté levantado
#   Params:     analysis_slug -> Es el id del proyecto en formato "slug"
#               (ej: "Proyecto BaLIza v16" -> "proyecto_baliza_v16"). Actúa como ID único del proyecto
#               del usuario.
#   Retorno:    Devuelve un JSON con los resultados
#=======================================================================================================
@app.post("/analisis/{analysis_slug}/aceptacion/filter-geo")
def filter_aceptacion_geo(request: Request, analysis_slug: str, payload: FilterRequest, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    require_llm()
    return aux_filter_aceptacion_geo(db, analysis_slug, payload, current_user)


@app.get("/analisis/{analysis_id}/aceptacion/download-txt")
async def download_aceptacion_txt(request: Request, analysis_id: str, current_user: UserResponse = Depends(get_current_user)):
    txt_path = await aux_download_aceptacion_txt(analysis_id, current_user)
    return FileResponse(path=txt_path, filename=f"informe_aceptacion_{analysis_id}.txt", media_type="text/plain")


########################################################################
#  Grafo y visual semántico
########################################################################

@app.get("/analisis/{analysis_slug}/grafo")
async def get_grafo(
    analysis_slug: str,
    nivel: str = Query("topic", pattern="^(topic|usuario)$"),
    plataforma: str = Query("todas"),
    geo: str = Query(""),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return await aux_get_grafo(db, analysis_slug, nivel, plataforma, geo, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error construyendo grafo: {exc}")


@app.get("/analisis/{analysis_slug}/visual-semantico")
async def get_visual_semantico(
    analysis_slug: str,
    plataforma: str = Query("todas"),
    geo: str = Query(""),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return await aux_get_visual_semantico(db, analysis_slug, plataforma, geo, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error construyendo visualizaciones: {exc}")


########################################################################
#  Páginas de usuario
########################################################################

#======================================================================================================
# function -> mis_analisis
#   Objetivo:   Muestra todos los análisis del usuario. El progreso en el que se encuentran, si desean
#               detenerlo, eliminarlo o descargarse el documento.
#   Retorno:    Devuelve el HTML de "mis_analisis.html" de todos sis pe¡o
#=======================================================================================================
@app.get("/mis-analisis")
def mis_analisis(request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        analyses = get_analyses_for_user(db, current_user.id)
        result = [
            {
                "id":           a["id"],
                "project_name": a["project_name"],
                "project_url":  a["project_name_slug"],
                "status":       a["status"],
                "progress":     a["progress"],
                "download_url": a["download_url"]
            }
            for a in analyses
        ]
        return templates.TemplateResponse("mis_analisis.html", {"request": request, "analyses": result, "user": current_user})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/analizar-datasets")
def analizar_datasets(request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    analyses = aux_mis_analisis(current_user)
    return templates.TemplateResponse("analizar_datasets.html", {"request": request, "user": current_user, "analyses": analyses})

#======================================================================================================
# function -> delete_analysis_endpoint
#   Objetivo:   Elimina el proyecto con id "slug" de la BBDD y las carpetas de ese proyecto en el usuario
#               detenerlo, eliminarlo o descargarse el documento.
#   Retorno:    Devuelve el HTML de "mis_analisis.html" de todos sis pe¡o
#=======================================================================================================
@app.delete("/analisis/{slug}/delete", status_code=status.HTTP_200_OK)
def delete_analysis_endpoint(slug: str, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db), ctx: dict = Depends(get_request_context)):
    return ejecutar_eliminacion_sana_by_slug(
        db=db, slug=slug, user_id=current_user.id,
        ctx=ctx, actor_username=current_user.username,
    )


@app.get("/configuracion")
def configuracion(request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    return templates.TemplateResponse("ajustes.html", {"request": request, "user": current_user})


@app.get("/suscripciones")
def suscripciones(request: Request, current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    return templates.TemplateResponse("suscripciones.html", {"request": request, "user": current_user})


########################################################################
#  API sidebar
########################################################################

@app.get("/api/proyectos-sidebar")
def get_projects_sidebar(current_user: UserResponse = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        analyses = get_analyses_for_user(db, current_user.id)
        return [
            {
                "id":           a["id"],
                "project_name": a["project_name"],
                "project_url":  a["project_name_slug"],
                "status":       a["status"],
                "progress":     a["progress"]
            }
            for a in analyses
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


########################################################################
#  Léxico semántico v2
########################################################################

@app.get("/analisis/{analysis_slug}/lexico-semantico-v2")
async def get_lexico_semantico_v2(
    analysis_slug: str,
    plataforma: str = Query("todas"),
    geo: str = Query(""),
    top_nube: int = Query(15, ge=5, le=50),
    top_topicos: int = Query(15, ge=5, le=30),
    current_user: UserResponse = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return await aux_get_lexico_semantico_v2(db, analysis_slug, plataforma, geo, top_nube, top_topicos, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error construyendo léxico semántico: {exc}")


########################################################################
#  Startup
########################################################################

@app.on_event("startup")
def startup():
    db = SessionLocal()
    try:
        create_test_users(db)
    finally:
        db.close()
