from celery_app import celery_app
from logica_FORMAT import (
    backend_analisis, crear_config_dinamica, relanzar_llm_si_pendiente,
    ejecutar_scoreop_desde_logica, asegurar_nubes_dashboard, calcular_dashboard_base,
)
import os, json, csv
from pathlib import Path
from fastapi.responses import JSONResponse
import uuid
from bbdd.response.user_response import UserResponse
#from aux_main.aux_main_general import aux_ejecutar_analisis


from bbdd.database import SessionLocal
from bbdd.models_all import Analysis, AnalysisTask, TaskStatus
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
@celery_app.task(bind=True)
def reanudar_analisis_pendiente_task(self, analysis_id: int, task_id: int):
    """Reanuda un análisis interrumpido: LLM pendiente → ScoreOP → dashboard_data.json."""
    db = SessionLocal()
    try:
        TaskService.update_status(db=db, task_id=task_id, status=TaskStatus.RUNNING,
                                   message="Reanudando análisis pendiente…")
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not analysis:
            TaskService.update_status(db=db, task_id=task_id, status=TaskStatus.FAILED,
                                       error_message="Análisis no encontrado")
            return

        u_conf = crear_config_dinamica(analysis.analysis_config or {})
        u_conf.general["output_folder"] = str(Path(analysis.output_folder or u_conf.general.get("output_folder", "")).resolve())
        output_folder_path = Path(u_conf.general["output_folder"])

        relanzar_llm_si_pendiente(u_conf)

        from clean_project.analysis.scoreop_calculator import ejecutar_scoreop_desde_logica
        from clean_project.analysis.first_report import cargar_datos_para_reporte, generar_excel_sentimiento
        ejecutar_scoreop_desde_logica(u_conf)

        all_rows = cargar_datos_para_reporte(u_conf)
        if all_rows:
            df_final, _ = generar_excel_sentimiento(all_rows, output_folder_path)
            if df_final is not None and not df_final.empty:
                df_final.rename(columns={"sentimiento": "SENTIMIENTO", "topic": "TOPIC",
                                          "contenido": "CONTENIDO", "fecha": "FECHA"}, inplace=True)
                df_final.attrs["output_folder"] = str(output_folder_path)
                dashboard_base = calcular_dashboard_base(df_final)
                dashboard_base["raw_data"] = df_final.fillna("").to_dict("records")
                with open(output_folder_path / "dashboard_data.json", "w", encoding="utf-8") as f:
                    json.dump(dashboard_base, f, indent=2, default=str)

        TaskService.update_status(db=db, task_id=task_id, status=TaskStatus.COMPLETED,
                                   message="Análisis reanudado ✓", progress_percent=100)
    except Exception as e:
        TaskService.update_status(db=db, task_id=task_id, status=TaskStatus.FAILED,
                                   error_message=str(e))
        raise
    finally:
        db.close()