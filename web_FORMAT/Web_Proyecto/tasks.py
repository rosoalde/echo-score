from celery_app import celery_app
from logica_FORMAT import backend_analisis
import os, json, csv
from pathlib import Path
from fastapi.responses import JSONResponse
import uuid
from bbdd.response.user_response import UserResponse
#from aux_main.aux_main_general import aux_ejecutar_analisis


from bbdd.database import SessionLocal
from bbdd.models_all import AnalysisTask, TaskStatus
from datetime import datetime
from aux_main.task_service import TaskService
import time
import asyncio
from sqlalchemy.orm import Session

from aux_main.aux_main_general import ejecutar_eliminacion_sana_by_id

@celery_app.task(bind=True)
def ejecutar_analisis_task(self, data: dict, analysis_id:int=None, task_id: int = None):
    """Tarea real que ejecuta el análisis completo"""
    db = SessionLocal()
    try:
        # Marcar inicio
        TaskService.update_status(
            db=db, task_id=task_id,
            status=TaskStatus.RUNNING,
            message="Iniciando análisis de scraping",
        )
         
        # ... tu lógica de backend_analisis ...
        print("########## ENTRADA #############")
        resultado = asyncio.run(backend_analisis(db, data, analysis_id, task_id))
        print("########## SALIDA #############")
        # Actualizar progreso periódicamente
        '''
        TaskService.update_status(
            db=db, task_id=task_id,
            status=TaskStatus.COMPLETED,
            progress_percent=100,
            message="Análisis completado"
        )
        '''
        return resultado
    
    except Exception as e:
        TaskService.update_status(
            db=db,
            task_id=task_id,
            status=TaskStatus.FAILED,
            error_message=str(e)
        )
        ejecutar_eliminacion_sana_by_id(db, analysis_id)
        raise
    finally:
        db.close()
