from unittest import result

from fastapi import FastAPI, Request, Form, status, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Body
from types import SimpleNamespace
from pydantic import BaseModel, Field
from typing import List
import json
import subprocess
import zipfile
import os, csv, io
import uuid
from pathlib import Path
from datetime import datetime
#from logica import backend_analisis, backend_analisis, generar_keywords_con_ia
from logica_FORMAT import backend_analisis
from logica_FORMAT import generar_keywords_con_ia
from logica_FORMAT import recalcular_filas_incompletas
from starlette.middleware.sessions import SessionMiddleware
import asyncio
from temp_json import sync_analysis_db
import base64

from tasks import ejecutar_analisis_task, prueba_task
from celery.result import AsyncResult
#from celery_app import celery_app

import pandas as pd 
from bbdd.repositories.user_repo import UserRepositoryCSV
from logica_FORMAT import backend_analisis, generar_keywords_con_ia, calcular_dashboard_base

app = FastAPI()

user_repo = UserRepositoryCSV()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

#CRISTHIAN (FALTA AÚN )
#result = celery_app.send_task("logica.backend_analisis", args=[data])

from pathlib import Path

SECRET_FILE = Path("../secret_key_servidor.txt")


def load_secret_key():
    if not SECRET_FILE.exists():
        raise RuntimeError("❌ No se encontró el archivo de SECRET_KEY")
    
    with open(SECRET_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if line.startswith("SECRET_KEY="):
                return line.split("=", 1)[1]

    raise RuntimeError("❌ SECRET_KEY no encontrado en el archivo")

SECRET_KEY = load_secret_key()


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="session",
    https_only=False  # True en producción
)
'''
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, unique=True)
    password_hash = Column(String)

'''
def get_users():
    users = []
    with open("static/bbdd/bbdd_acceso.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            users.append(row)
    return users

#def get_current_user(request: Request):
def get_current_user(request: Request):
    return request.session.get("user")
    '''
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    
    return {
        "user_id": user_id,
        "username": request.session.get("user")
    }
    '''

def require_role(required_roles: list):
    def role_checker(request: Request):
        user = request.session.get("user")

        if not user:
            raise HTTPException(status_code=401, detail="No autenticado")

        if user.get("role") not in required_roles:
            raise HTTPException(
                status_code=403,
                detail="No tienes permisos para realizar esta acción"
            )

        return user

    return role_checker

def require_login(request: Request):
    user_id = request.session.get("user")
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado"
        )
    
    return request.session.get("user")
    '''
    return {
        "user_id": user_id,
        "username": request.session.get("user").username
    }
    '''
'''
def require_login(request: Request):
    user = request.cookies.get("session")
    if not user:
        # No logueado → redirigir al login
        raise HTTPException(
            status_code=401,
            detail="No autenticado"
        )
    return user
'''
# Usuario de ejemplo
USUARIO = "admin"
CONTRASENA = "1234"

# Para almacenar sesión en memoria (simple)
SESSIONS = set()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


ANALYSIS_STORE = {}

class ResultItem(BaseModel):
    social: str
    success: bool

class AnalisisData(BaseModel):
    project_name: str
    tema: str = Field(..., alias="asistente")
    keywords: str
    start_date: str
    end_date: str
    sources: List[str]
    population_scope: str = Field(..., alias="population")
    results: List[ResultItem]

@app.get("/")
def root(request: Request):
    user = get_current_user(request)

    if not user:
        # No logueado → login
        return RedirectResponse(url="/login", status_code=302)

    # Logueado → análisis
    return RedirectResponse(url="/analisis", status_code=302)


@app.get("/analisis")
def home(request: Request, user = Depends(require_login)):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "resultado": None, "user":user}
    )

from uuid import uuid4
SIMULATED_ANALYSES = {}
FUENTES = ["twitter", "facebook", "instagram"]
#parte 2
@app.post("/ejecutar-analisis_CELERY")
async def ejecutar_analisis_CELERY(request: Request, user=Depends(require_role(["admin", "analista"]))):
    data = await request.json()
    data["username"] = user.get("username")
    data["role"] = user.get("role")

    # Generar un ID de análisis único
    analysis_id = str(uuid4())

    # Inicializar estado simulado
    SIMULATED_ANALYSES[analysis_id] = {
        "status": "iniciado",
        "progress": 0,
        "current_source": None,
        "sources": [{"name": s, "status": "iniciado"} for s in FUENTES]
    }

    # Lanzar Celery (por ahora solo prueba_task)
    # celery_result = ejecutar_analisis_task.delay(data)
    celery_result = prueba_task.delay()

    # Retorna ID del análisis al frontend
    return JSONResponse({
        "status": "ok",
        "analysis_id": analysis_id,
        "message": "El análisis se está ejecutando en segundo plano."
    })



@app.get("/estado-analisis2")
async def estado_analisis2(analysis_id: str):
    """
    Devuelve el estado actual del análisis.
    Por ahora simula progreso secuencial por fuente.
    """
    if analysis_id not in SIMULATED_ANALYSES:
        return JSONResponse({"status": "error", "message": "analysis_id no encontrado"}, status_code=404)

    state = SIMULATED_ANALYSES[analysis_id]

    # Simulación de avance
    if state["status"] != "terminado":
        # Avanza el progreso de la fuente actual
        for source in state["sources"]:
            if source["status"] != "terminado":
                state["current_source"] = source["name"]
                if "progress" not in source:
                    source["progress"] = 0
                source["progress"] += 10  # Incremento de simulación
                if source["progress"] >= 100:
                    source["progress"] = 100
                    source["status"] = "terminado"
                break

        # Actualizar estado global y porcentaje
        total = len(state["sources"])
        done = sum(1 for s in state["sources"] if s["status"] == "terminado")
        state["progress"] = int((done / total) * 100)
        if done == total:
            state["status"] = "terminado"
            state["current_source"] = None
        else:
            state["status"] = "progress"

    return JSONResponse(state)


@app.post("/ejecutar-analisis")
async def ejecutar_analisis(request: Request, user = Depends(require_role(["admin", "analista"]))):
    data = await request.json()
    print("Datos recibidos: ", data)

    # Creamos un ID temporal solo para el nombre del archivo CSV local de FastAPI (opcional)
    temp_id = str(uuid.uuid4())

    try:
        # 📁 Carpeta por usuario
        analysis_path = os.path.join("files", user.get("username"))
        os.makedirs(analysis_path, exist_ok=True)
        
        data["username"] = user.get("username")
        data["role"] = user.get("role")

        # 1. EJECUTAR LÓGICA (Aquí se crea el ID real y se guarda en analysis_db.json)
        resultado = backend_analisis(data)

        # 2. OBTENER EL ID REAL GENERADO POR LOGICA.PY
        real_analysis_id = resultado.get("analysis_id")
        
        if not real_analysis_id:
            raise Exception("El backend no devolvió un analysis_id válido.")

        # ===============================
        # 📊 Leer dashboard_data.json
        # ===============================
        output_folder = resultado.get("output_folder")
        dashboard_data = {}
        
        if output_folder:
            dashboard_path = Path(output_folder) / "dashboard_data.json"
            if dashboard_path.exists():
                with open(dashboard_path, "r", encoding="utf-8") as f:
                    dashboard_data = json.load(f)

        # Guardar CSV simple de registro (opcional)
        file_path = f"files/analisis_{real_analysis_id}.csv"
        os.makedirs("files", exist_ok=True)
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Red", "Éxito"])
            for r in data["results"]:
                writer.writerow([r["social"], r["success"]])

        # 3. RETORNAR EL ID REAL AL FRONTEND
        return JSONResponse({
            "status": "ok",
            "user_id": real_analysis_id,  # <--- ¡AQUÍ ESTÁ EL CAMBIO IMPORTANTE!
            "data": resultado,
            "dashboard": dashboard_data,
        })

    except Exception as e:
        print("Error ejecutando análisis:", e)
        # Importante imprimir el traceback completo si puedes
        import traceback
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": str(e)})

#================  Romina ================     

# @app.get("/analisis/{analysis_id}/download")
# def download_analysis(analysis_id: str):
#     #analysis = ANALYSIS_STORE.get(analysis_id)


#     zip_buffer = download_files(analysis_id)

#     return StreamingResponse(
#         zip_buffer,
#         media_type="application/zip",
#         headers={
#             "Content-Disposition": "attachment; filename=archivos.zip"
#         }
#     )

#     if not analysis:
#         raise HTTPException(status_code=404, detail="Análisis no encontrado")

#     return FileResponse(
#         path=analysis["file_path"],
#         filename="resultados.csv",
#         media_type="text/csv"
#     )
@app.get("/analisis/{analysis_id}/download")
def download_analysis(analysis_id: str, user = Depends(require_role(["admin", "analista"]))):

    #================  Romina ================
    # ANALYSIS_DB = Path("analysis_db.json")
    ANALYSIS_DB = Path("analysis_db.json").resolve()
    #=================  Romina ================

    if not ANALYSIS_DB.exists():
        raise HTTPException(status_code=404, detail="No hay análisis guardados")

    
    db = json.loads(ANALYSIS_DB.read_text())

    analysis = next((a for a in db if a["id"] == analysis_id), None)

    if user["role"] != "admin" and analysis["username"] != user["username"]:
        raise HTTPException(status_code=403)
    
    project_name = analysis.get("project_name", f"proyecto_{analysis_id}")
    project_name = project_name.replace(" ", "_")
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")

    folder = Path(analysis["output_folder"])

    if not folder.exists():
        raise HTTPException(status_code=404, detail="Carpeta de resultados no existe")

    # zip_path = folder / "resultados.zip"

    # with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
    #     for file in folder.iterdir():
    #         if file.is_file() and file != zip_path:
    #             zipf.write(file, arcname=file.name)
    # return FileResponse(zip_path, filename="resultados.zip")
     # 🔹 Creamos zip en memoria, nunca en la carpeta
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipf:

        # =========================
        # 1️⃣ Archivos permitidos
        # =========================
        for file in folder.iterdir():

            if not file.is_file():
                continue

            if (
                file.name == "reporte_analisis.xlsx"
                or file.name.endswith("datos_con_pilares.csv")
                or file.name.endswith("datos_sentimiento_filtrados.csv") 
                or file.name.endswith("_global_dataset.csv")
                or file.name.endswith("datos_combinados.csv")
                # or file.name == "dashboard_data.json"
                # or file.suffix.lower() == ".png"
            ):
                arcname = f"{project_name}/{file.name}"
                zipf.write(file, arcname=arcname)

        # =========================
        # 2️⃣ Crear TXT informativo
        # =========================
        info_text = f"""
        INFORMACIÓN DEL ANÁLISIS
        ------------------------

        Proyecto: {analysis.get("project_name")}
        ID: {analysis.get("id")}
        Usuario: {analysis.get("username")}

        Tema:
        {analysis.get("tema", "No disponible")}

        Keywords:
        {analysis.get("keywords", "No disponible")}

        Fuentes:
        {", ".join(analysis.get("sources", []))}

        Idiomas:
        {", ".join(analysis.get("languages", []))}

        Población objetivo:
        {analysis.get("population_scope", "No especificado")}

        Fecha inicio búsqueda:
        {analysis.get("start_date", "No disponible")}

        Fecha fin búsqueda:
        {analysis.get("end_date", "No disponible")}

        Fecha creación análisis:
        {analysis.get("created_at")}
        """

        zipf.writestr(f"{project_name}/info_busqueda.txt", info_text.strip())


    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=resultados_{analysis_id}.zip"}
    )


#================  Romina ================     


@app.get("/login")
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login")
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    user = authenticate_user(username, password)

    if not user:
        # ❌ No autenticado
        request.session.clear()
        request.session["login_error"] = "Usuario o contraseña incorrectos"

        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    # ✅ Login correcto
    request.session["user"] = {
        "user_id": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "email": user["email"],
        "phone": user["phone"]
    }

    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    
@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

#================  Romina ================
# @app.get("/mis-analisis")
# def mis_analisis(request: Request, user = Depends(require_login)):
    
#     analyses = get_analyses_for_user(user)

#     return templates.TemplateResponse(
#         "mis_analisis.html",
#         {
#             "request": request,
#             "user": request.session.get("user"),
#             "analyses": analyses
#         }
#     )
@app.get("/mis-analisis")
def mis_analisis(request: Request):
    user = request.session.get("user")

    if not user:
        return RedirectResponse("/")

    analyses = get_analyses_for_user(user)

    return templates.TemplateResponse(
        "mis_analisis.html",
        {
            "request": request,
            "analyses": analyses,
            "user": user
        }
    )

#=================  Romina ================


@app.post("/generate_keywords")
async def generate_keywords(request: Request):#, data: dict = Body(...)):
    data = await request.json()
     # Debug para ver qué llega exactamente desde el navegador
    raw_body = await request.body()
    print("RAW BODY:", raw_body)

    context = data.get("context", "")
    languages = data.get("languages", [])  # <-- leer idiomas
    poblacion = data.get("population", "") # <--- Recibirlo del JS
    keywords = generar_keywords_con_ia(context, languages, poblacion)
    
    ##....Del backend al frontend
    #keywords = ["ayuda", "pruebas", "balizav16", "ayuda", "pruebas", "balizav16","ayuda", "pruebas", "balizav16","ayuda", "pruebas", "balizav16"]

    # '''-------------ELIMINAR-------------'''
    keywords = ["ayuda", "balizas v16"]
    # '''-----------FIN ELIMINAR-----------'''
    return JSONResponse({"success": True, "keywords": keywords})


@app.get("/analisis/{analysis_id}")
def view_analysis(request: Request, analysis_id: str, user=Depends(require_login)):
    analysis = get_analysis_by_id(analysis_id, user)

    return templates.TemplateResponse(
        "analysis_dashboard.html",
        {
            "request": request,
            "user": user,
            "analysis": analysis
        }
    )

@app.get("/analizar-datasets")
def analizar_datasets(request: Request, user = Depends(require_login)):

    analyses = get_analyses_for_user(user)

    return templates.TemplateResponse(
        "analizar_datasets.html",
        {
            "request": request,
            "user": request.session.get("user"),
            "analyses": analyses
        }
    )

@app.get("/configuracion")
def mis_analisis(request: Request):
    user = request.session.get("user")

    if not user:
        return RedirectResponse("/")

    analyses = get_analyses_for_user(user)

    return templates.TemplateResponse(
        "ajustes.html",
        {
            "request": request,
            "analyses": analyses,
            "user": user
        }
    )

@app.get("/suscripciones")
def mis_analisis(request: Request):
    user = request.session.get("user")

    if not user:
        return RedirectResponse("/")

    analyses = get_analyses_for_user(user)

    return templates.TemplateResponse(
        "suscripciones.html",
        {
            "request": request,
            "analyses": analyses,
            "user": user
        }
    )
####
####
####simular logica.py
####
####
####

RUTA_ARCHIVOS = "/../web_FastAPI/Web_Proyecto"
#RUTA_ARCHIVOS = ""
def download_files(user_id: str):

    buffer = io.BytesIO()
    zip_path =  os.path.join(RUTA_ARCHIVOS, user_id)

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(zip_path):
            for file in files:
                ruta_completa = os.path.join(root, file)
                # 🔹 ignorar cualquier zip existente para no incluirlo dentro del zip
                if ruta_completa.endswith(".zip"):
                    continue
                ruta_zip = os.path.relpath(ruta_completa, zip_path)
                zipf.write(ruta_completa, ruta_zip)

    buffer.seek(0)
    return buffer

def authenticate_user(username: str, password: str):
    users = get_users()

    for user in users:
        if user["username"] == username and password == user["password"]:
            return user
    
    return None

def authenticate_user_NEXT(username: str, password: str):
    user = user_repo.authenticate(username, password)
    if not user:
        return None
    # Convertir dataclass a diccionario para la sesión
    return {
        "user_id": str(user.id),
        "username": user.username,
        "role": user.role,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name
    }

def update_user_data_NEXT(user_id: int, first_name: str = None, last_name: str = None, phone: str = None, password: str = None):
    user = next((u for u in user_repo.get_all() if u.id == user_id), None)
    if not user:
        raise Exception("Usuario no encontrado")

    if first_name is not None:
        user.first_name = first_name
    if last_name is not None:
        user.last_name = last_name
    if phone is not None:
        user.phone = phone
    if password is not None:
        user.hashed_password = pwd_context.hash(password)

    user_repo.update(user)


#ESTA FUNCIÓN ES PROVISIONAL, PUES DEBERÍA DE CONSULTAR A LA BBDD NO MIRARLO DIRECTAMENTE
def get_analyses_for_user_FUTURO(user_id: str):
    DATASET_DIR= Path("../datasets")
    user_dir = DATASET_DIR / f"{user_id}"
    analyses = []

    if not user_dir.exists():
        return []
    
    for analysis_dir in user_dir.iterdir():
        metadata_file = analysis_dir / "metadata.json"
        
        if not metadata_file.exists():
            continue
        with open(metadata_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        
        analyses.append({
            "id": analysis_dir.name,
            "project_name": meta.get("project_name"),
            "tema": meta.get("tema"),
            "created_at": datetime.strptime(meta.get("created_at"), "%d-%m-%Y %H:%M"),
            "sources": meta.get("sources", []),
            "languages": meta.get("languages", []),
            "keywords": meta.get("keywords", []),
            "population_scope": meta.get("population_scope", []),
            "status": meta.get("status", "unkown"),
            "progress": meta.get("progress", 0),
            "download_url": f"/analisis/{analysis_dir.name}/{project_name}/download"
        })
        

##USAR ESTE CUANDO PONGAMOS UNA BBDD
#================  Romina ================  
def get_analyses_for_user(user: dict):
#def get_analyses_for_user(user_id: str):
    # DATASET_DIR= Path("../datasets")
    # user_dir = DATASET_DIR / f"{user_id}"
    # '''
    # if not user_dir.exists():
    #     return []
    # '''
    # analyses = []
    # '''
    # for analysis_dir in user_dir.iterdir():
    #     metadata_file = analysis_dir / "metadata.json"

    #     if not metadata_file.exists():
    #         continue

    #     with open(metadata_file, "r", encoding="utf-8") as f:
    #         meta = json.load(f)

    #     analyses.append({
    #         "id": analysis_dir.name,
    #         "project_name": meta.get("project_name"),
    #         "created_at": meta.get("created_at"),
    #         "sources": meta.get("sources", []),
    #         "languages": meta.get("languages", []),
    #         "status": meta.get("status", "unknown"),
    #         "download_url": f"/analisis/{analysis_dir.name}/download"
    #     })
    # '''
    # ####este es un ejemplo
    # dt = datetime.strptime("2026-01-15 18:32", "%Y-%m-%d %H:%M")
    # ejemplo = {
    #     "id": "a1b2c3d4",
    #     "project_name": "Análisis Marca 2026",
    #     "created_at": dt.strftime("%d-%m-%Y %H:%M"),
    #     "order_by": dt,
    #     "sources": ["twitter", "reddit", "youtube"],
    #     "keywords": ["hola", "caracola"],
    #     "languages": ["Castellano", "Inglés"],
    #     "status": "completed",
    #     "progress": 100,
    #     "download_url": "/analisis/a1b2c3d4/download"
    # }
    # dt = datetime.strptime("2026-01-20 15:15", "%Y-%m-%d %H:%M")
    # ejemplo2 = {
    #     "id": "a1b2c3d5",
    #     "project_name": "Análisis Marca 2030",
    #     "created_at": dt.strftime("%d-%m-%Y %H:%M"),
    #     "order_by": dt,
    #     "sources": ["twitter", "reddit", "youtube"],
    #     "keywords": ["hola", "caracola"],
    #     "languages": ["Castellano", "Inglés"],
    #     "status": "completed",
    #     "progress": 100,
    #     "download_url": "/analisis/a1b2c3d5/download"
    # }
    # dt = datetime.strptime("2026-01-25 11:00", "%Y-%m-%d %H:%M")
    # ejemplo3 = {
    #     "id": "a1b2c3d5",
    #     "project_name": "Análisis Marca 2035",
    #     "created_at": dt.strftime("%d-%m-%Y %H:%M"),
    #     "order_by": dt,
    #     "sources": ["twitter", "reddit", "youtube"],
    #     "keywords": ["hola", "caracola"],
    #     "languages": ["Castellano", "Inglés"],
    #     "status": "progress",
    #     "progress": 0.25,
    #     "download_url": "/analisis/a1b2c3d5/download"
    # }
    # analyses.append(ejemplo)
    # analyses.append(ejemplo2)
    # analyses.append(ejemplo3)
    # ##se acaba el ejemplo

    # # Más recientes primero
    # return sorted(analyses, key=lambda x: x["order_by"], reverse=True)

    #================  Romina ================
    # ANALYSIS_DB = Path("analysis_db.json")
    ANALYSIS_DB = Path("analysis_db.json").resolve()
    print("Syncing DB en:", ANALYSIS_DB)
    #=================  Romina ================

    # 🔄 Sync automático inteligente (solo agrega nuevos)
    db = sync_analysis_db()

    # Si no hay datos, devolver lista vacía
    if not db:
        return []

    user_analyses = []

    for a in db:
        if a.get("username") != user.get("username"):
            continue

        # Saltar eliminados
        if a.get("status") == "deleted":
            continue

        created_raw = a.get("created_at")
        try:
            created_dt = datetime.fromisoformat(created_raw)
            created_str = created_dt.strftime("%d-%m-%Y %H:%M")
        except:
            created_dt = datetime.min
            created_str = "Fecha desconocida"

        folder_name = Path(a.get("output_folder")).name if a.get("output_folder") else a.get("project_name")

        user_analyses.append({
            "id": a.get("id"),
            "project_name": folder_name,
            "created_at": created_str,
            "order_by": created_dt,
            "status": a.get("status", "completed"),
            "progress": 100 if a.get("status") == "completed" else 0,
            "download_url": f"/analisis/{a.get('id')}/download"
        })

    # Ordenar más nuevos primero
    return sorted(user_analyses, key=lambda x: x["order_by"], reverse=True)
    #================  Romina ================  

def get_analysis_by_id(analysis_id: str, user: dict):
    ANALYSIS_DB = Path("analysis_db.json").resolve()

    if not ANALYSIS_DB.exists():
        raise HTTPException(status_code=404, detail="No hay análisis guardados")

    db = json.loads(ANALYSIS_DB.read_text())

    analysis = next(
        (a for a in db 
         if a.get("id") == analysis_id 
         and a.get("username") == user.get("username")),
        None
    )

    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")

    return analysis

# ... imports existentes ...

@app.get("/analisis/{analysis_id}/dashboard")
def get_dashboard_data(analysis_id: str, request: Request):
    """
    Lee el dashboard. Si detecta formato antiguo o error, regenera desde el CSV
    manejando correctamente el separador (; o ,).
    """
    # 1. Buscar en la "Base de Datos"
    ANALYSIS_DB = Path("analysis_db.json").resolve()
    if not ANALYSIS_DB.exists():
        return JSONResponse({"error": "Base de datos no encontrada"}, status_code=404)

    try:
        db = json.loads(ANALYSIS_DB.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"error": f"Error leyendo DB: {str(e)}"}, status_code=500)
    
    analysis = next((a for a in db if a["id"] == analysis_id), None)
    if not analysis:
        return JSONResponse({"error": "Análisis no encontrado"}, status_code=404)

    folder = Path(analysis["output_folder"])
    # ============================================================
# 🔥 ASEGURAR QUE LAS NUBES EXISTEN (Lazy Generation)
# ============================================================
    try:
        asegurar_nubes_dashboard(folder)
    except Exception as e:
        print(f"⚠️ Error asegurando nubes: {e}")
    json_path = folder / "dashboard_data.json"
    
    # Buscamos el CSV
    csv_path = folder / "datos_sentimiento_filtrados.csv"
    if not csv_path.exists():
        csv_path = folder / "tiktok_global_dataset.csv"

    data = {}
    regenerar = False

    # 2. Intentar leer JSON existente
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            # Si falta la clave "kpis", es viejo.
            if "kpis" not in data:
                print(f"⚠️ JSON antiguo detectado en {analysis_id}. Regenerando...")
                regenerar = True
        except Exception as e:
            print(f"⚠️ Error leyendo JSON: {e}")
            regenerar = True
    else:
        regenerar = True

    # 3. REGENERACIÓN AUTOMÁTICA
    if regenerar:
        if csv_path.exists():
            try:
                print(f"🔄 Recalculando dashboard desde: {csv_path.name}")
                
                # --- CORRECCIÓN DEL SEPARADOR ---
                try:

                    print(f"\n=== Analizando {csv_path.name} ===")
                    with open(csv_path, 'r', encoding='utf-8') as f:
                        primera_linea = f.readline()
                        sep = ';' if ';' in primera_linea else ','

                    df = pd.read_csv(csv_path, sep=sep, encoding='utf-8', engine='python', on_bad_lines='skip')    

                except:
                    print(f"❌ Error leyendo CSV con pandas. Intentando lectura manual para detectar problemas.")

                    

                # Normalizar nombres (Mapeo seguro)
                # Tu CSV ya tiene mayúsculas, pero por si acaso mapeamos las minúsculas
                col_map = {
                    "titulo": "TITULO", "comentario_texto": "CONTENIDO", 
                    "cuerpo": "CUERPO", "fuente": "FUENTE", 
                    "fecha": "FECHA", "sentimiento": "SENTIMIENTO",
                    "topic": "TOPIC", "likes": "LIKES", 
                    "comments": "COMMENTS", "shares": "SHARES", 
                    "followers": "FOLLOWERS"
                }
                df.rename(columns=col_map, inplace=True)

                # Limpieza de Textos
                cols_str = ["TITULO", "CUERPO", "CONTENIDO", "TOPIC", "FUENTE", "ID"]
                for c in cols_str:
                    if c in df.columns: df[c] = df[c].fillna("").astype(str)
                
                # Limpieza de Métricas (Tus nuevos campos)
                cols_num = ["LIKES", "COMMENTS", "SHARES", "FOLLOWERS", "VIEWS"]
                for c in cols_num:
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0).astype(int)
                    else:
                        df[c] = 0 # Si no existe, rellenamos con 0

                # Limpieza Sentimiento
                if "SENTIMIENTO" in df.columns:
                    df["SENTIMIENTO"] = pd.to_numeric(df["SENTIMIENTO"], errors='coerce').fillna(0).astype(int)

                # 🔥 CALCULAR ESTRUCTURA NUEVA
                df = recalcular_filas_incompletas(df)
                data = calcular_dashboard_base(df)
                
                # Agregar raw_data
                data["raw_data"] = df.fillna("").to_dict(orient="records")
                
                # Recalcular Topics
                if "TOPIC" in df.columns:
                    df["TOPIC"] = (
                        df["TOPIC"]
                        .fillna("")
                        .astype(str)
                        .str.strip()
                        .str.lower()
                    )
                    topics = (
                        df.groupby("TOPIC")
                        .agg(
                            volumen=("TOPIC", "count"),
                            sentimiento_prom=("SENTIMIENTO", "mean")
                        )
                        .reset_index()
                        .to_dict(orient="records")
                    )
                    data["topics"] = topics
                else:
                    data["topics"] = []

                # 💾 GUARDAR EL JSON NUEVO
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)
                
                print("✅ Dashboard regenerado correctamente.")

            except Exception as e:
                print(f"❌ Error fatal regenerando dashboard: {e}")
                import traceback
                traceback.print_exc()
                data = {}
        else:
            data = {}

    # 4. Cargar imágenes
    data["nubes"] = {}
    for img_file in folder.glob("nube_*.png"):
        try:
            with open(img_file, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                data["nubes"][img_file.stem] = encoded_string
        except Exception:
            pass

    return JSONResponse(data)

# Modelo para recibir la lista de términos
class FilterRequest(BaseModel):
    terms: List[str] = []      # Filtro Geográfico
    custom_topic: str = ""     # Filtro por Topic (Nuevo)

@app.post("/analisis/{analysis_id}/filter-geo")
def filter_analysis_geo(analysis_id: str, payload: FilterRequest, user=Depends(require_login)):
    """
    Recibe términos geográficos Y/O un topic personalizado.
    """
    print(f"📍 Petición de filtro para {analysis_id}. Geo: {payload.terms}, Topic: {payload.custom_topic}")

    # 1. Buscar ruta del análisis
    ANALYSIS_DB = Path("analysis_db.json").resolve()
    if not ANALYSIS_DB.exists():
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")

    db = json.loads(ANALYSIS_DB.read_text(encoding="utf-8"))
    analysis = next((a for a in db if a["id"] == analysis_id), None)

    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")

    output_folder = Path(analysis["output_folder"])
    
    # Buscar CSV fuente
    csv_path = output_folder / "datos_sentimiento_filtrados.csv"
    if not csv_path.exists():
        csv_path = output_folder / "tiktok_global_dataset.csv" 
        if not csv_path.exists():
             raise HTTPException(status_code=404, detail="Archivo de datos (CSV) no encontrado")

    try:
        from logica_FORMAT import filtrar_y_recalcular_dashboard
        
        # Ejecutar lógica con AMBOS parámetros
        new_dashboard_data = filtrar_y_recalcular_dashboard(
            csv_path=csv_path,
            output_folder=output_folder,
            terminos_geo=payload.terms,
            custom_topic=payload.custom_topic # <--- NUEVO PARÁMETRO
        )
        
        return JSONResponse(content=jsonable_encoder(new_dashboard_data))

    except Exception as e:
        print(f"❌ Error en filtro avanzado: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    
from logica_FORMAT import ejecutar_indicador_aceptacion, asegurar_nubes_dashboard


@app.post("/analisis/{analysis_id}/aceptacion")
async def run_aceptacion(
    analysis_id: str,
    user = Depends(require_login)
):
    
    if user["role"] == "user":
            filename = f"datos/user/user_{analysis_id}.json"

            if not os.path.exists(filename):
                raise HTTPException(
                    status_code=404,
                    detail=f"No existe el archivo {filename}"
                )

            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)

            return JSONResponse(content=jsonable_encoder({
                "ok": True,
                **data
            }))
    
    try:
        result = await asyncio.to_thread(
            ejecutar_indicador_aceptacion,
            analysis_id,
            user
        )
        return JSONResponse(content=jsonable_encoder({
            "ok": True,
            **result
        }))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
import math

def clean_nans(obj):
    if isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nans(v) for v in obj]
    elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0
    else:
        return obj

@app.post("/analisis/{analysis_id}/aceptacion/filter-geo")
def filter_aceptacion_geo(
    analysis_id: str,
    payload: FilterRequest,
    user=Depends(require_login)
):
    from logica_FORMAT import recalcular_aceptacion_filtrada
    
    result = recalcular_aceptacion_filtrada(
        analysis_id=analysis_id,
        user=user,
        terminos_geo=payload.terms
    )
    result = clean_nans(result)
    return JSONResponse(content=jsonable_encoder(result))

@app.get("/analisis/{analysis_id}/aceptacion/download-txt")
def download_aceptacion_txt(analysis_id: str, user = Depends(require_login)):
    # 1. Buscar el análisis en la DB para obtener la ruta de la carpeta
    ANALYSIS_DB = Path("analysis_db.json").resolve()
    if not ANALYSIS_DB.exists():
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")
    
    db = json.loads(ANALYSIS_DB.read_text(encoding="utf-8"))
    analysis = next((a for a in db if a["id"] == analysis_id), None)
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")

    # 2. Construir la ruta al archivo .txt
    output_folder = Path(analysis["output_folder"])
    txt_path = output_folder / "aceptacion_global.txt"

    # 3. Verificar si el archivo existe
    if not txt_path.exists():
        raise HTTPException(status_code=404, detail="El informe TXT aún no ha sido generado.")

    # 4. Devolver el archivo para descarga
    return FileResponse(
        path=txt_path, 
        filename=f"informe_aceptacion_{analysis_id}.txt",
        media_type="text/plain"
    )