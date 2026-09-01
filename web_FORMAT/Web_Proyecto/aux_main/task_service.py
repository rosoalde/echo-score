from sqlalchemy.orm import Session
from sqlalchemy import BigInteger
from bbdd.models_all import AnalysisTask, TaskStatus, TaskTypeEnum
from datetime import datetime, timezone
from typing import Optional, Dict, Any


class TaskService:
    @staticmethod
    def create_task(
        db: Session,
        task_type: TaskTypeEnum,
        analysis_id: BigInteger = None,
        user_id: BigInteger = None,
        input_config: Dict[str, Any] = None,
        priority: int = 5
    ) -> AnalysisTask:
        """Crea una nueva tarea en la base de datos"""
        task = AnalysisTask(
            analysis_id=analysis_id,
            user_id=user_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            input_config=input_config or {},
            priority=priority
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def update_status(
        db: Session,
        task_id: BigInteger,
        status: TaskStatus,
        task_type: TaskTypeEnum = None,
        message: str = None,
        progress_percent: int = None,
        current_step: str = None,
        processed_items: int = None,
        error_message: str = None,
        error_traceback: str = None,
        output_summary: Dict = None
    ) -> AnalysisTask:
        """Actualiza el estado de una tarea"""
        task = db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()
        if not task:
            raise ValueError(f"Tarea {task_id} no encontrada")

        task.status = status
        task.updated_at = datetime.now(timezone.utc)
        
        if task_type is not None:
            task.task_type = task_type

        if message:
            task.message = message
        if progress_percent is not None:
            task.progress_percent = progress_percent
        if current_step:
            task.current_step = current_step
        if processed_items is not None:
            task.processed_items = processed_items
        if error_message:
            task.error_message = error_message
        if error_traceback:
            task.error_traceback = error_traceback
        if output_summary:
            task.output_summary = output_summary

        # Actualizar timestamps según estado
        if status == TaskStatus.QUEUED and not task.queued_at:
            task.queued_at = datetime.now(timezone.utc)
        elif status == TaskStatus.RUNNING and not task.started_at:
            task.started_at = datetime.now(timezone.utc)
        elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            task.finished_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def get_task(db: Session, task_id: BigInteger) -> Optional[AnalysisTask]:
        """Obtiene una tarea por ID"""
        return db.query(AnalysisTask).filter(AnalysisTask.id == task_id).first()

    @staticmethod
    def get_tasks_by_analysis(db: Session, analysis_id: BigInteger) -> list[AnalysisTask]:
        """Obtiene todas las tareas de un análisis"""
        return db.query(AnalysisTask).filter(
            AnalysisTask.analysis_id == analysis_id
        ).order_by(AnalysisTask.created_at.desc()).all()