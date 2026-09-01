from fastapi import FastAPI, Request, Response, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, StreamingResponse

from sqlalchemy.orm import Session


from aux_func.aux_class import AdminResponse

from aux_func.aux_admin import get_current_admin, get_current_admin_optional, aux_login_post

from bbdd.database import get_db
from bbdd.models_all import User, Role, TaskLog, AnalysisTask, TaskStatus, TaskTypeEnum, Analysis, AnalysisStatus, UserSession, AuditLog
from aux_func.aux_celery import celery_admin
from aux_func.audit_service import AuditService, EventType, EventCategory, EventResult, ActorType
import urllib.parse
from sqlalchemy import func as sa_func, text
from datetime import datetime, timedelta
import urllib.request
import urllib.error
import socket
import time
import os

################################# Me quedé aquí, empezar a partir de aquí

app = FastAPI()

templates = Jinja2Templates("templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from aux_func.aux_metrics_auth import verificar_metrics_token

Instrumentator().instrument(app)

METRICS_PATH = os.getenv("METRICS_PATH", "/_metrics_09_81")

@app.get(METRICS_PATH, include_in_schema=False)
def metrics(_: bool = Depends(verificar_metrics_token)):
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


##################################################
# FUNCIONES AUXILIARES

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

##################################################
@app.get("/")
def root(current_user: AdminResponse | None = Depends(get_current_admin_optional)):

    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/administracion", status_code=302)


@app.get("/login")
def login(request: Request, current_user: AdminResponse | None = Depends(get_current_admin_optional)):
    if not current_user:
        return templates.TemplateResponse("login.html", {"request": request, "error": None})
    return RedirectResponse(url="/administracion", status_code=302)

@app.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    token_user = aux_login_post(username, password)

    if not token_user:
        return JSONResponse(
            status_code=401,
            content={"detail": "Usuario o contraseña incorrectos"}
        )

    response = RedirectResponse(
        url="/administracion",
        status_code=303
    )

    response.set_cookie(
        key="access_token",
        value=token_user,
        httponly=True,
        samesite="lax",
        secure=False
    )

    return response

@app.post("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key="access_token")
    return response


@app.get("/administracion")
async def dashboard(request: Request, current_user: AdminResponse = Depends(get_current_admin)):
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request
        }
    )

#############################################################################################
#############################################################################################
#############################################################################################
#############################################################################################
#############################################################################################


##########################                  USUARIOS               ##########################
#
#
#############################################################################################

@app.get("/users")
def users_page(
    request: Request,
    current_user: AdminResponse = Depends(get_current_admin)
):

    return templates.TemplateResponse(
        "users.html",
        {
            "request": request
        }
    )

@app.get("/api/users/{user_id}")
def get_user_detail(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    # análisis del usuario, resumen general (no todos los campos, solo lo necesario para vista)
    analyses = (
        db.query(Analysis)
        .filter(Analysis.user_id == user_id)
        .order_by(Analysis.created_at.desc())
        .all()
    )

    analyses_by_status = {}
    for a in analyses:
        key = a.status.value if hasattr(a.status, "value") else a.status
        analyses_by_status[key] = analyses_by_status.get(key, 0) + 1

    last_session = (
        db.query(UserSession)
        .filter(UserSession.user_id == user_id)
        .order_by(UserSession.created_at.desc())
        .first()
    )

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "roles": [{"id": r.id, "name": r.name} for r in user.roles],
        "sessions_count": len(user.sessions),
        "last_session": {
            "ip_address": last_session.ip_address,
            "created_at": last_session.created_at,
            "expires_at": last_session.expires_at,
            "revoked": last_session.revoked,
        } if last_session else None,
        "tasks_count": len(user.tasks),
        "analyses": {
            "total": len(analyses),
            "by_status": analyses_by_status,
            "items": [
                {
                    "id": a.id,
                    "project_name": a.project_name,
                    "slug": a.slug,
                    "status": a.status.value if hasattr(a.status, "value") else a.status,
                    "progress_percent": a.progress_percent,
                    "created_at": a.created_at,
                }
                for a in analyses[:20]
            ],
        },
    }
    
@app.get("/api/users")
def get_users(
    page: int = 1,
    page_size: int = 25,
    search: str = "",
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    try:

        query = db.query(User)

        if search:
            query = query.filter(User.username.ilike(f"%{search}%"))

        total = query.count()

        users = (
            query
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "items": [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "is_active": u.is_active,
                    "is_verified": u.is_verified,
                    "created_at": u.created_at,
                    "roles": [{"id": r.id, "name": r.name} for r in u.roles],
                    "analyses_count": len(u.analyses),
                    "sessions_count": len(u.sessions),
                }
                for u in users
            ],
            "total": total,
            "page": page,
            "total_pages": max(1, (total // page_size) + 1)
        }

    except Exception as e:
        print("🔥 ERROR USERS API:", e)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.post("/api/users")
def create_user(
    data: dict,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    role_ids = data.get("roles") or []

    user = User(
        username=data["username"],
        email=data["email"],
        first_name=data["first_name"],
        last_name=data.get("last_name"),
        hashed_password=get_password_hash(data["password"]),  # aquí deberías hashear
        is_active=data.get("is_active", True),
        is_verified=data.get("is_verified", False),
    )

    if role_ids:
        user.roles = db.query(Role).filter(Role.id.in_(role_ids)).all()

    db.add(user)
    db.commit()
    db.refresh(user)

    return {"ok": True, "id": user.id}

@app.patch("/api/users/{user_id}")
def update_user(
    user_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    # "roles" no es una columna normal, es una relación M2M -> se trata aparte
    role_ids = data.pop("roles", None)

    for key, value in data.items():
        setattr(user, key, value)

    if role_ids is not None:
        user.roles = db.query(Role).filter(Role.id.in_(role_ids)).all()

    db.commit()

    return {"ok": True}


@app.get("/api/roles")
def get_roles(
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    roles = db.query(Role).all()

    return {"items": [{"id": r.id, "name": r.name} for r in roles]}


@app.delete("/api/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    db.delete(user)
    db.commit()

    return {"ok": True}

@app.post("/api/users/{user_id}/password")
def change_password(
    user_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    user.hashed_password = get_password_hash(data["password"])  # hash aquí

    db.commit()

    return {"ok": True}


@app.post("/api/users/bulk-delete")
def bulk_delete(
    data: dict,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    ids = data.get("ids", [])

    db.query(User).filter(User.id.in_(ids)).delete(synchronize_session=False)

    db.commit()

    return {"ok": True}


#############################################################################################
#############################################################################################
#############################################################################################


##########################                  LOGS                   ##########################
#
#
#############################################################################################

@app.get("/logs")
def logs_page(
    request: Request,
    current_user: AdminResponse = Depends(get_current_admin)
):

    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request
        }
    )


@app.get("/api/logs")
def get_logs(
    page: int = 1,
    page_size: int = 25,
    level: str = "",
    task_id: int | None = None,
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    try:

        query = db.query(TaskLog)

        if level:
            query = query.filter(TaskLog.level == level.upper())

        if task_id:
            query = query.filter(TaskLog.task_id == task_id)

        if search:
            query = query.filter(TaskLog.message.ilike(f"%{search}%"))

        if date_from:
            query = query.filter(TaskLog.created_at >= date_from)

        if date_to:
            query = query.filter(TaskLog.created_at <= date_to)

        query = query.order_by(TaskLog.created_at.desc())

        total = query.count()

        logs = (
            query
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        items = []
        for log in logs:
            task = log.task  # puede ser None si el log no está ligado a una tarea, o si la tarea fue borrada

            items.append({
                "id": log.id,
                "level": log.level,
                "message": log.message,
                "meta_data": log.meta_data,
                "created_at": log.created_at,
                "task_id": log.task_id,
                "task_type": task.task_type.value if task else None,
                "task_status": task.status.value if task else None,
            })

        total_pages = max(1, (total + page_size - 1) // page_size)

        return {
            "items": items,
            "total": total,
            "page": page,
            "total_pages": total_pages
        }

    except Exception as e:
        print("🔥 ERROR LOGS API:", e)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.get("/api/logs/summary")
def logs_summary(
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    rows = db.query(TaskLog.level, sa_func.count(TaskLog.id)).group_by(TaskLog.level).all()

    by_level = {lvl: count for lvl, count in rows}

    last_24h = db.query(sa_func.count(TaskLog.id)).filter(
        TaskLog.created_at >= datetime.utcnow() - timedelta(hours=24)
    ).scalar()

    return {
        "total": sum(by_level.values()),
        "by_level": by_level,
        "last_24h": last_24h or 0
    }


@app.delete("/api/logs/purge")
def purge_logs(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    threshold = datetime.utcnow() - timedelta(days=days)

    deleted = (
        db.query(TaskLog)
        .filter(TaskLog.created_at < threshold)
        .delete(synchronize_session=False)
    )

    db.commit()

    return {"ok": True, "deleted": deleted}


#############################################################################################
#############################################################################################
#############################################################################################


##########################            TAREAS / PROCESOS            ##########################
#
#
#############################################################################################

def _serialize_task(t: AnalysisTask) -> dict:
    return {
        "id": t.id,
        "analysis_id": t.analysis_id,
        "analysis_name": t.analysis.project_name if t.analysis else None,
        "user_id": t.user_id,
        "username": t.user.username if t.user else None,
        "celery_task_id": t.celery_task_id,
        "task_type": t.task_type.value if t.task_type else None,
        "status": t.status.value if t.status else None,
        "priority": t.priority,
        "progress_percent": t.progress_percent,
        "total_items": t.total_items,
        "processed_items": t.processed_items,
        "current_step": t.current_step,
        "message": t.message,
        "error_message": t.error_message,
        "created_at": t.created_at,
        "queued_at": t.queued_at,
        "started_at": t.started_at,
        "finished_at": t.finished_at,
    }


@app.get("/tasks")
def tasks_page(
    request: Request,
    current_user: AdminResponse = Depends(get_current_admin)
):

    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "task_statuses": [s.value for s in TaskStatus],
            "task_types": [t.value for t in TaskTypeEnum],
        }
    )


@app.get("/api/tasks")
def get_tasks(
    page: int = 1,
    page_size: int = 25,
    status_filter: str = "",
    task_type: str = "",
    analysis_id: int | None = None,
    user_id: int | None = None,
    search: str = "",
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    try:

        query = db.query(AnalysisTask)

        if status_filter:
            query = query.filter(AnalysisTask.status == status_filter.lower())

        if task_type:
            query = query.filter(AnalysisTask.task_type == task_type.lower())

        if analysis_id:
            query = query.filter(AnalysisTask.analysis_id == analysis_id)

        if user_id:
            query = query.filter(AnalysisTask.user_id == user_id)

        if search:
            like = f"%{search}%"
            query = query.filter(
                (AnalysisTask.message.ilike(like)) |
                (AnalysisTask.error_message.ilike(like)) |
                (AnalysisTask.current_step.ilike(like))
            )

        query = query.order_by(AnalysisTask.created_at.desc())

        total = query.count()

        tasks = (
            query
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        total_pages = max(1, (total + page_size - 1) // page_size)

        return {
            "items": [_serialize_task(t) for t in tasks],
            "total": total,
            "page": page,
            "total_pages": total_pages
        }

    except Exception as e:
        print("🔥 ERROR TASKS API:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/tasks/summary")
def tasks_summary(
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    rows = db.query(AnalysisTask.status, sa_func.count(AnalysisTask.id)).group_by(AnalysisTask.status).all()

    by_status = {}
    for status_value, count in rows:
        key = status_value.value if hasattr(status_value, "value") else status_value
        by_status[key] = count

    return {"total": sum(by_status.values()), "by_status": by_status}


@app.get("/api/tasks/{task_id}")
def get_task_detail(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()

    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})

    logs = (
        db.query(TaskLog)
        .filter(TaskLog.task_id == task_id)
        .order_by(TaskLog.created_at.desc())
        .limit(200)
        .all()
    )

    data = _serialize_task(task)
    data["input_config"] = task.input_config
    data["output_summary"] = task.output_summary
    data["logs"] = [
        {"id": l.id, "level": l.level, "message": l.message, "created_at": l.created_at}
        for l in logs
    ]

    return data


@app.post("/api/tasks/{task_id}/retry")
def retry_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()

    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})

    task.status = TaskStatus.PENDING
    task.error_message = None
    task.progress_percent = 0
    task.processed_items = 0
    task.started_at = None
    task.finished_at = None
    db.commit()

    try:
        # Lanzamos por NOMBRE, sin importar el módulo real de la tarea
        # (admin-api no comparte volumen con Web_Proyecto)
        async_result = celery_admin.send_task(
            "tasks.ejecutar_analisis_task",
            kwargs={
                "data": task.input_config or {},
                "analysis_id": task.analysis_id,
                "task_id": task.id,
            },
        )
        task.celery_task_id = async_result.id
        db.commit()

    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error_message = f"Error al relanzar la tarea: {e}"
        db.commit()
        return JSONResponse(status_code=500, content={"error": str(e)})

    return {"ok": True, "celery_task_id": task.celery_task_id}


@app.post("/api/tasks/{task_id}/revoke")
def revoke_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()

    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})

    if task.celery_task_id:
        try:
            celery_admin.control.revoke(task.celery_task_id, terminate=True, signal="SIGKILL")
        except Exception as e:
            print("🔥 ERROR REVOKE:", e)

    task.status = TaskStatus.CANCELLED
    task.finished_at = datetime.utcnow()
    if not task.error_message:
        task.error_message = "Cancelada manualmente desde el panel de administración"

    db.commit()

    return {"ok": True}


@app.delete("/api/tasks/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()

    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})

    db.delete(task)
    db.commit()

    return {"ok": True}


@app.get("/api/workers")
def get_workers(
    current_user: AdminResponse = Depends(get_current_admin)
):

    try:
        insp = celery_admin.control.inspect(timeout=2)

        active = insp.active() or {}
        reserved = insp.reserved() or {}
        stats = insp.stats() or {}
        pong = insp.ping() or {}

        names = set(active) | set(reserved) | set(stats) | set(pong)

        workers = []
        for name in names:
            worker_stats = stats.get(name) or {}
            workers.append({
                "name": name,
                "online": name in pong,
                "active_tasks": len(active.get(name, [])),
                "reserved_tasks": len(reserved.get(name, [])),
                "concurrency": (worker_stats.get("pool") or {}).get("max-concurrency"),
            })

        return {"workers": workers}

    except Exception as e:
        print("🔥 ERROR WORKERS API:", e)
        return JSONResponse(status_code=500, content={"error": str(e), "workers": []})


#############################################################################################
#############################################################################################
#############################################################################################


##########################                 ANÁLISIS                ##########################
#
# NOTA IMPORTANTE: admin-api no monta el volumen de Web_Proyecto, así que estas rutas
# solo tocan la base de datos. El borrado de la carpeta física (output_folder) sigue
# viviendo en ejecutar_eliminacion_sana_by_id() dentro de Web_Proyecto y NO se ejecuta
# desde aquí para evitar borrar rutas a ciegas sin acceso real al filesystem.
#
#############################################################################################

def _serialize_analysis(a: Analysis, with_tasks: bool = False) -> dict:
    data = {
        "id": a.id,
        "project_name": a.project_name,
        "slug": a.slug,
        "status": a.status.value if hasattr(a.status, "value") else a.status,
        "progress_percent": a.progress_percent,
        "output_folder": a.output_folder,
        "user_id": a.user_id,
        "username": a.user.username if a.user else None,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
        "tasks_count": len(a.tasks),
    }
    if with_tasks:
        data["analysis_config"] = a.analysis_config
        data["tasks"] = [_serialize_task(t) for t in a.tasks]
    return data


@app.get("/analyses")
def analyses_page(
    request: Request,
    current_user: AdminResponse = Depends(get_current_admin)
):

    return templates.TemplateResponse(
        "analyses.html",
        {
            "request": request,
            "analysis_statuses": [s.value for s in AnalysisStatus],
        }
    )


@app.get("/api/analyses")
def get_analyses(
    page: int = 1,
    page_size: int = 25,
    status_filter: str = "",
    user_id: int | None = None,
    search: str = "",
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    try:

        query = db.query(Analysis)

        if status_filter:
            query = query.filter(Analysis.status == status_filter.lower())

        if user_id:
            query = query.filter(Analysis.user_id == user_id)

        if search:
            like = f"%{search}%"
            query = query.filter(
                (Analysis.project_name.ilike(like)) | (Analysis.slug.ilike(like))
            )

        query = query.order_by(Analysis.created_at.desc())

        total = query.count()

        analyses = (
            query
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        total_pages = max(1, (total + page_size - 1) // page_size)

        return {
            "items": [_serialize_analysis(a) for a in analyses],
            "total": total,
            "page": page,
            "total_pages": total_pages
        }

    except Exception as e:
        print("🔥 ERROR ANALYSES API:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/analyses/summary")
def analyses_summary(
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    rows = db.query(Analysis.status, sa_func.count(Analysis.id)).group_by(Analysis.status).all()

    by_status = {}
    for status_value, count in rows:
        key = status_value.value if hasattr(status_value, "value") else status_value
        by_status[key] = count

    return {"total": sum(by_status.values()), "by_status": by_status}


@app.get("/api/analyses/{analysis_id}")
def get_analysis_detail(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()

    if not analysis:
        return JSONResponse(status_code=404, content={"error": "Analysis not found"})

    return _serialize_analysis(analysis, with_tasks=True)


@app.patch("/api/analyses/{analysis_id}/status")
def update_analysis_status(
    analysis_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()

    if not analysis:
        return JSONResponse(status_code=404, content={"error": "Analysis not found"})

    new_status = data.get("status")
    valid_values = [s.value for s in AnalysisStatus]

    if new_status not in valid_values:
        return JSONResponse(
            status_code=400,
            content={"error": f"Estado inválido. Valores permitidos: {valid_values}"}
        )

    analysis.status = new_status
    db.commit()

    return {"ok": True, "status": analysis.status.value if hasattr(analysis.status, "value") else analysis.status}


@app.delete("/api/analyses/{analysis_id}")
def delete_analysis_record(
    analysis_id: int,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):
    """
    OJO: esto borra SOLO la fila en base de datos (y en cascada sus AnalysisTask/TaskLog).
    NO borra la carpeta output_folder en disco -- ver nota al principio de esta sección.
    """

    analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()

    if not analysis:
        return JSONResponse(status_code=404, content={"error": "Analysis not found"})

    db.delete(analysis)
    db.commit()

    return {"ok": True, "warning": "Registro eliminado. La carpeta en disco NO se ha tocado."}


#############################################################################################
#############################################################################################
#############################################################################################


##########################                DASHBOARD                 #########################
#
#
#############################################################################################

@app.get("/api/dashboard/stats")
def dashboard_stats(
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    try:
        total_users = db.query(sa_func.count(User.id)).scalar() or 0
        active_users = db.query(sa_func.count(User.id)).filter(User.is_active == True).scalar() or 0
        verified_users = db.query(sa_func.count(User.id)).filter(User.is_verified == True).scalar() or 0

        analyses_rows = db.query(Analysis.status, sa_func.count(Analysis.id)).group_by(Analysis.status).all()
        analyses_by_status = {}
        for s, c in analyses_rows:
            analyses_by_status[s.value if hasattr(s, "value") else s] = c

        tasks_rows = db.query(AnalysisTask.status, sa_func.count(AnalysisTask.id)).group_by(AnalysisTask.status).all()
        tasks_by_status = {}
        for s, c in tasks_rows:
            tasks_by_status[s.value if hasattr(s, "value") else s] = c

        errors_24h = db.query(sa_func.count(TaskLog.id)).filter(
            TaskLog.level == "ERROR",
            TaskLog.created_at >= datetime.utcnow() - timedelta(hours=24)
        ).scalar() or 0

        return {
            "users": {
                "total": total_users,
                "active": active_users,
                "verified": verified_users,
            },
            "analyses": {
                "total": sum(analyses_by_status.values()),
                "active": analyses_by_status.get("active", 0),
                "by_status": analyses_by_status,
            },
            "tasks": {
                "total": sum(tasks_by_status.values()),
                "running": tasks_by_status.get("running", 0),
                "failed": tasks_by_status.get("failed", 0),
                "by_status": tasks_by_status,
            },
            "errors_24h": errors_24h,
        }

    except Exception as e:
        print("🔥 ERROR DASHBOARD STATS:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


def _check_db(db: Session) -> dict:
    try:
        start = time.time()
        db.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


def _check_redis() -> dict:
    try:
        start = time.time()
        conn = celery_admin.connection()
        conn.ensure_connection(max_retries=1, timeout=2)
        conn.close()
        return {"ok": True, "latency_ms": round((time.time() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "detail": str(e)}


def _check_workers() -> dict:
    try:
        insp = celery_admin.control.inspect(timeout=2)
        pong = insp.ping() or {}
        active = insp.active() or {}
        total_active_tasks = sum(len(v) for v in active.values())
        return {
            "ok": len(pong) > 0,
            "workers_online": len(pong),
            "active_tasks": total_active_tasks,
        }
    except Exception as e:
        return {"ok": False, "detail": str(e), "workers_online": 0, "active_tasks": 0}


def _check_llm() -> dict:
    # Servicio externo, no gestionado por docker-compose. URL configurable por .env.
    # admin-api necesita "extra_hosts: host.docker.internal:host-gateway" para
    # poder resolver el host cuando el vLLM corre en la propia máquina host.
    url = os.getenv("LLM_HEALTH_URL", "http://host.docker.internal:8001/health")

    try:
        start = time.time()
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            ok = 200 <= resp.status < 300
        return {"ok": ok, "url": url, "latency_ms": round((time.time() - start) * 1000, 1)}
    except (urllib.error.URLError, socket.timeout, ConnectionRefusedError) as e:
        return {"ok": False, "url": url, "detail": str(e)}
    except Exception as e:
        return {"ok": False, "url": url, "detail": str(e)}


@app.get("/api/dashboard/health")
def dashboard_health(
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    return {
        "db": _check_db(db),
        "redis": _check_redis(),
        "workers": _check_workers(),
        "llm": _check_llm(),
    }


#############################################################################################
#############################################################################################
#############################################################################################


##########################               AUDITORÍA                 #########################
#
# Distinta de "Logs" (TaskLog = ejecución de tareas de Celery). AuditLog es
# el rastro de quién hizo qué acción sensible (login, CRUD, permisos,
# seguridad...), venga de un usuario normal, del propio admin, o del sistema.
#
#############################################################################################

def _serialize_audit(a: AuditLog) -> dict:
    return {
        "id": a.id,
        "event_type": a.event_type,
        "category": a.category,
        "result": a.result,
        "actor_type": a.actor_type,
        "actor_id": a.actor_id,
        "actor_username": a.actor_username,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "target_label": a.target_label,
        "ip_address": a.ip_address,
        "port_address": a.port_address,
        "user_agent": a.user_agent,
        "session_id": a.session_id,
        "request_id": a.request_id,
        "message": a.message,
        "has_attachment": bool(a.attachment_path),
        "attachment_size": a.attachment_size,
        "created_at": a.created_at,
    }


@app.get("/auditoria")
def auditoria_page(
    request: Request,
    current_user: AdminResponse = Depends(get_current_admin)
):

    return templates.TemplateResponse(
        "auditoria.html",
        {
            "request": request,
            "event_types": [e.value for e in EventType],
            "categories": [c.value for c in EventCategory],
            "results": [r.value for r in EventResult],
            "actor_types": [a.value for a in ActorType],
        }
    )


@app.get("/api/audit")
def get_audit_logs(
    page: int = 1,
    page_size: int = 25,
    event_type: str = "",
    category: str = "",
    result_filter: str = "",
    actor_type: str = "",
    actor_username: str = "",
    target_type: str = "",
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    try:

        query = db.query(AuditLog)

        if event_type:
            query = query.filter(AuditLog.event_type == event_type)

        if category:
            query = query.filter(AuditLog.category == category)

        if result_filter:
            query = query.filter(AuditLog.result == result_filter)

        if actor_type:
            query = query.filter(AuditLog.actor_type == actor_type)

        if actor_username:
            query = query.filter(AuditLog.actor_username.ilike(f"%{actor_username}%"))

        if target_type:
            query = query.filter(AuditLog.target_type == target_type)

        if search:
            query = query.filter(AuditLog.message.ilike(f"%{search}%"))

        if date_from:
            query = query.filter(AuditLog.created_at >= date_from)

        if date_to:
            query = query.filter(AuditLog.created_at <= date_to)

        query = query.order_by(AuditLog.created_at.desc())

        total = query.count()

        rows = (
            query
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        total_pages = max(1, (total + page_size - 1) // page_size)

        return {
            "items": [_serialize_audit(a) for a in rows],
            "total": total,
            "page": page,
            "total_pages": total_pages
        }

    except Exception as e:
        print("🔥 ERROR AUDIT API:", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/audit/summary")
def audit_summary(
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    total = db.query(sa_func.count(AuditLog.id)).scalar() or 0

    by_result = dict(
        db.query(AuditLog.result, sa_func.count(AuditLog.id)).group_by(AuditLog.result).all()
    )
    by_category = dict(
        db.query(AuditLog.category, sa_func.count(AuditLog.id)).group_by(AuditLog.category).all()
    )

    last_24h = db.query(sa_func.count(AuditLog.id)).filter(
        AuditLog.created_at >= datetime.utcnow() - timedelta(hours=24)
    ).scalar() or 0

    security_events = by_category.get("security", 0)

    return {
        "total": total,
        "by_result": by_result,
        "by_category": by_category,
        "last_24h": last_24h,
        "security_events": security_events,
    }


@app.get("/api/audit/{audit_id}")
def get_audit_detail(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):

    entry = db.query(AuditLog).filter(AuditLog.id == audit_id).first()

    if not entry:
        return JSONResponse(status_code=404, content={"error": "Audit log not found"})

    data = _serialize_audit(entry)
    # lee del fichero si el payload se offloadeó por ser grande (ver audit_service.py)
    data["details"] = AuditService.get_full_details(entry)

    return data


@app.delete("/api/audit/purge-blobs")
def purge_audit_blobs(
    days: int = 180,
    db: Session = Depends(get_db),
    current_user: AdminResponse = Depends(get_current_admin)
):
    """
    OJO: esto NO borra filas de auditoría (esas se quedan para siempre).
    Solo libera los ficheros pesados (`attachment_path`) más antiguos que
    `days`; la fila queda marcada como '_purged' pero sigue existiendo.
    """
    deleted = AuditService.purge_old_blobs(db, days=days)
    return {"ok": True, "deleted": deleted}


#############################################################################################
#############################################################################################
#############################################################################################


##########################             MONITORIZACIÓN               ##########################
#
# Prometheus/Grafana escuchan en 127.0.0.1 del host (solo accesible por
# túnel SSH), pero admin-api SÍ puede consultar a Prometheus por la red
# interna de Docker (http://prometheus:9090), independientemente de ese
# bind a loopback -- por eso estas tarjetas de resumen funcionan sin túnel,
# aunque Grafana en sí no se pueda embeber aquí.
#
#############################################################################################

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")


def _prom_query(query: str):
    """Instant query contra la API HTTP de Prometheus. Devuelve el primer valor numérico, o None."""
    try:
        url = f"{PROMETHEUS_URL}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
        with urllib.request.urlopen(url, timeout=3) as resp:
            import json as _json
            data = _json.loads(resp.read())

        result = data.get("data", {}).get("result", [])
        if not result:
            return None

        value = result[0]["value"][1]
        return float(value)

    except Exception as e:
        print(f"🔥 ERROR PROM QUERY ({query}):", e)
        return None


def _prom_query_vector(query: str):
    """
    Igual que _prom_query pero para consultas con varios resultados
    (ej. topk(...)). Devuelve una lista de {labels: {...}, value: float}.
    """
    try:
        url = f"{PROMETHEUS_URL}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
        with urllib.request.urlopen(url, timeout=3) as resp:
            import json as _json
            data = _json.loads(resp.read())

        result = data.get("data", {}).get("result", [])

        return [
            {"labels": r.get("metric", {}), "value": float(r["value"][1])}
            for r in result
        ]

    except Exception as e:
        print(f"🔥 ERROR PROM QUERY VECTOR ({query}):", e)
        return []


def _prom_range_query(query: str, start: float, end: float, step: int):
    """
    Instant query -> punto único. Range query -> serie temporal completa.
    Devuelve lista de [timestamp, valor]. Si la query no agrega a una sola
    serie (ej. le falta un sum()/avg()), se coge la primera que devuelva
    Prometheus -- igual que ya hace _prom_query con las instant queries.
    """
    try:
        params = {"query": query, "start": start, "end": end, "step": step}
        url = f"{PROMETHEUS_URL}/api/v1/query_range?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=6) as resp:
            import json as _json
            data = _json.loads(resp.read())
        result = data.get("data", {}).get("result", [])
        if not result:
            return []
        return [[float(ts), float(val)] for ts, val in result[0]["values"]]
    except Exception as e:
        print(f"🔥 ERROR PROM RANGE QUERY ({query}):", e)
        return []


@app.get("/monitorizacion")
def monitorizacion_page(
    request: Request,
    current_user: AdminResponse = Depends(get_current_admin)
):
    return templates.TemplateResponse("monitorizacion.html", {"request": request})


@app.get("/api/monitoring/summary")
def monitoring_summary(
    current_user: AdminResponse = Depends(get_current_admin)
):
    """
    Resumen "de un vistazo" con las métricas más importantes de cada
    subsistema. El detalle fino (histórico, por-contenedor, por-endpoint...)
    vive en Grafana, no aquí.
    """

    queries = {
        # Host (node-exporter)
        "cpu_pct": '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
        "ram_pct": '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100',
        "swap_pct": '(1 - (node_memory_SwapFree_bytes / node_memory_SwapTotal_bytes)) * 100',
        "disk_pct": '100 - ((node_filesystem_avail_bytes{mountpoint="/"} * 100) / node_filesystem_size_bytes{mountpoint="/"})',
        "load1": "node_load1",

        # Contenedores (cadvisor)
        "containers_running": 'count(count by (name) (container_last_seen{name!=""}))',

        # PostgreSQL
        "pg_connections": "sum(pg_stat_database_numbackends)",
        "pg_cache_hit_pct": (
            "sum(pg_stat_database_blks_hit) / "
            "(sum(pg_stat_database_blks_hit) + sum(pg_stat_database_blks_read)) * 100"
        ),

        # Redis
        "redis_memory_mb": "redis_memory_used_bytes / 1024 / 1024",
        "redis_hit_ratio_pct": (
            "redis_keyspace_hits_total / (redis_keyspace_hits_total + redis_keyspace_misses_total) * 100"
        ),

        # FastAPI (Web_Proyecto)
        "http_p95_ms": (
            'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="fastapi-web"}[5m])) by (le)) * 1000'
        ),
        "http_error_rate": (
            'sum(rate(http_requests_total{job="fastapi-web", status=~"5.."}[5m])) / '
            'sum(rate(http_requests_total{job="fastapi-web"}[5m])) * 100'
        ),

        # Celery -- confirmado contra tu celery-exporter real (danihodovic/celery-exporter)
        "celery_workers_online": "count(celery_worker_up == 1)",
        "celery_queue_length": "sum(celery_queue_length)",
        "celery_active_processes": "sum(celery_active_process_count)",
        "celery_tasks_succeeded": "sum(celery_task_succeeded_total)",
        "celery_tasks_failed": "sum(celery_task_failed_total)",
        "celery_tasks_retried": "sum(celery_task_retried_total)",
        "celery_runtime_p95_s": (
            "histogram_quantile(0.95, sum(rate(celery_task_runtime_bucket[15m])) by (le))"
        ),

        # Datos de usuario (datos/) -- estos SÍ son fiables, los generamos nosotros
        "data_total_bytes": "app_total_data_bytes",
        "data_last_refresh_seconds_ago": "time() - app_data_metrics_last_refresh_timestamp",
    }

    results = {key: _prom_query(q) for key, q in queries.items()}

    # top 5 usuarios por espacio ocupado (consulta aparte: devuelve varios resultados)
    top_users_raw = _prom_query_vector("topk(5, app_user_data_bytes)")
    results_top_users = [
        {"username": r["labels"].get("username", "?"), "bytes": r["value"]}
        for r in top_users_raw
    ]

    return {
        "metrics": results,
        "top_users_by_data": results_top_users,
        "prometheus_reachable": any(v is not None for v in results.values()),
    }


# (segundos_totales, step_en_segundos) -- step elegido para no pedir miles de
# puntos a Prometheus ni sobrecargar el gráfico en el navegador (~300-400 puntos)
RANGE_PRESETS = {
    "24h": (24 * 3600, 300),      # cada 5 min
    "7d": (7 * 24 * 3600, 1800),  # cada 30 min
    "30d": (30 * 24 * 3600, 7200),  # cada 2 h
}
@app.get("/api/monitoring/history")
def monitoring_history(
    range: str = "24h",
    current_user: AdminResponse = Depends(get_current_admin)
):
    """
    Series temporales para las gráficas del panel admin. Reutiliza las
    mismas PromQL que /api/monitoring/summary, pero con query_range en vez
    de query -- así no hay que mantener dos definiciones de cada métrica.
    """
    seconds, step = RANGE_PRESETS.get(range, RANGE_PRESETS["24h"])
    end = time.time()
    start = end - seconds
    queries = {
        "cpu_pct": '100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)',
        "ram_pct": '(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100',
        "disk_pct": '100 - ((node_filesystem_avail_bytes{mountpoint="/"} * 100) / node_filesystem_size_bytes{mountpoint="/"})',
        "http_requests_rate": 'sum(rate(http_requests_total{job="fastapi-web"}[5m]))',
        "http_p95_ms": (
            'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="fastapi-web"}[5m])) by (le)) * 1000'
        ),
        "http_error_rate": (
            'sum(rate(http_requests_total{job="fastapi-web", status=~"5.."}[5m])) / '
            'sum(rate(http_requests_total{job="fastapi-web"}[5m])) * 100'
        ),
        "celery_success_rate": "sum(rate(celery_task_succeeded_total[15m]))",
        "celery_failed_rate": "sum(rate(celery_task_failed_total[15m]))",
        "data_total_bytes": "app_total_data_bytes",
    }
    series = {key: _prom_range_query(q, start, end, step) for key, q in queries.items()}
    return {"range": range, "series": series}
