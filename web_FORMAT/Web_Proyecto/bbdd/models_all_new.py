from sqlalchemy import (
    Column, Integer, String, Text, Boolean,
    ForeignKey, TIMESTAMP, Enum, JSON, Float,
    UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func
from bbdd.database import Base
import enum


# =========================
# 🎯 ENUMS (Estados predefinidos)
# =========================
#
class TaskStatus(str, enum.Enum):
    PENDING = "pending"           # Esperando en cola
    QUEUED = "queued"             # En cola priorizada
    RUNNING = "running"           # Ejecutándose
    PAUSED = "paused"             # Pausado por usuario
    COMPLETED = "completed"       # Finalizado OK
    FAILED = "failed"             # Error no recuperable
    CANCELLED = "cancelled"       # Cancelado por usuario
    RETRYING = "retrying"         # Reintentando tras fallo


class TaskTypeEnum(str, enum.Enum):
    SCRAPING = "scraping"         # Recolección de datos
    CLEANING = "cleaning"         # Limpieza de datos
    ANALYSIS_LLM = "analysis_llm" # Análisis con LLM
    EXPORT = "export"             # Exportar resultados
    NOTIFICATION = "notification" # Enviar notificación


class AnalysisStatus(str, enum.Enum):
    DRAFT = "draft"               # Configurando, no iniciado
    ACTIVE = "active"             # Tiene tareas en curso
    COMPLETED = "completed"       # Todas las tareas OK
    ARCHIVED = "archived"         # Archivado por usuario
    ERROR = "error"               # Error general


########################################
class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=True, index=True)
    
    project_name = Column(Text)
    asistente = Column(Text)
    keywords = Column(Text),
    start_date = Column(TIMESTAMP)
    end_date = Column(TIMESTAMP)
    sources = Column(Text)
    languages = Column(Text)
    population = Column(Text),
    results = Column(Text)
    
    # Configuración
    task_type = Column(Enum(TaskTypeEnum), nullable=False, index=True)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, index=True)
    priority = Column(Integer, default=5)  # 1-10 (1 = máxima prioridad)
    
    # Progreso
    progress_percent = Column(Integer, default=0)  # 0-100
    current_step = Column(String(255))  # "Descargando página 5 de 100"
    total_items = Column(Integer)  # Total a procesar
    processed_items = Column(Integer, default=0)  # Procesados
    
    # Mensajes y errores
    message = Column(Text)  # Mensaje informativo
    error_message = Column(Text)  # Detalle de error si falla
    error_traceback = Column(Text)  # Stack trace para debugging
    
    # Ejecución
    worker_id = Column(String(100), index=True)  # ID del worker/contenedor
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    # Timestamps de ejecución
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    queued_at = Column(TIMESTAMP)  # Cuando entró en cola
    started_at = Column(TIMESTAMP)
    finished_at = Column(TIMESTAMP)
    estimated_completion = Column(TIMESTAMP)  # ETA calculada
    
    # Datos de entrada/salida
    input_config = Column(JSON)  # Config específica de la tarea
    output_summary = Column(JSON)  # Resumen de resultados
    
    # Relaciones
    analysis = relationship("Analysis", back_populates="tasks")
    logs = relationship("TaskLog", back_populates="task", cascade="all, delete-orphan")
    
    __table_args__ = (
        CheckConstraint('priority >= 1 AND priority <= 10', name='chk_priority_range'),
        CheckConstraint('progress_percent >= 0 AND progress_percent <= 100', name='chk_progress_range'),
    )
'''

    const payload = {
        project_name: formData.get("project_name"),
        asistente: formData.get("asistente"),
        keywords: keywords,
        start_date: formData.get("start_date"),
        end_date: formData.get("end_date"),
        sources: sources,
        languages: languages,
        population: formData.get("population") || "",
        results: sources.map(s => ({ social: s, success: true })) // placeholder
    };

'''

'''
# =========================
# 🔑 KEYWORDS (Búsqueda)
# =========================
class Keyword(Base):
    __tablename__ = "keywords"
    
    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True)
    
    keyword = Column(String(255), nullable=False, index=True)  # String, no Text (más eficiente)
    language = Column(String(10), default="es")
    weight = Column(Integer, default=1)  # Importancia/prioridad
    is_excluded = Column(Boolean, default=False)  # Palabras a excluir
    
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    analysis = relationship("Analysis", back_populates="keywords")
    
    __table_args__ = (
        UniqueConstraint('analysis_id', 'keyword', name='uix_analysis_keyword'),
    )

    
# =========================
# 📦 DATOS SCRAPEADOS (Resultados)
# =========================
class ScrapedData(Base):
    __tablename__ = "scraped_data"
    
    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("analysis_tasks.id", ondelete="SET NULL"), index=True)
    
    # Fuente
    source_type = Column(String(50), nullable=False, index=True)  # "twitter", "reddit", "news"
    source_url = Column(String(1000))
    source_id = Column(String(255), index=True)  # ID externo (tweet_id, etc.)
    
    # Contenido
    raw_content = Column(Text)  # HTML/texto original
    cleaned_content = Column(Text)  # Texto limpio
    title = Column(String(500))
    author = Column(String(255))
    
    # Metadata
    published_at = Column(TIMESTAMP, index=True)  # Fecha original del contenido
    language = Column(String(10))
    sentiment_score = Column(Float)  # -1.0 a 1.0 (análisis previo)
    engagement_metrics = Column(JSON)  # Likes, shares, etc.
    
    # Estado de procesamiento
    is_processed = Column(Boolean, default=False)
    processing_metadata = Column(JSON)  # Resultados de NLP, entidades, etc.
    
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    analysis = relationship("Analysis", back_populates="scraped_data")
    task = relationship("AnalysisTask")


# =========================
# 🧠 CONCLUSIONES LLM (Análisis final)
# =========================1
class AnalysisConclusion(Base):
    __tablename__ = "analysis_conclusions"
    
    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("analysis_tasks.id", ondelete="SET NULL"))
    
    # Configuración usada
    llm_model = Column(String(50), nullable=False)  # "gpt-4", "claude-3", etc.
    prompt_used = Column(Text)
    temperature = Column(Float)
    
    # Resultado
    summary = Column(Text)  # Resumen ejecutivo
    key_findings = Column(JSON)  # Lista de hallazgos clave
    themes = Column(JSON)  # Temas identificados con pesos
    sentiment_analysis = Column(JSON)  # Análisis de sentimiento global
    recommendations = Column(JSON)  # Recomendaciones generadas
    
    # Métricas
    tokens_used = Column(Integer)
    cost_estimate = Column(Float)  # Costo estimado en USD
    processing_time_seconds = Column(Integer)
    
    # Calificación por usuario
    user_rating = Column(Integer)  # 1-5 estrellas
    user_feedback = Column(Text)
    
    created_at = Column(TIMESTAMP, server_default=func.now())
    
    analysis = relationship("Analysis", back_populates="conclusions")
    task = relationship("AnalysisTask")


# =========================
# 📈 NOTIFICACIONES (Sistema de alertas)
# =========================
class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    type = Column(String(50), nullable=False)  # "task_completed", "analysis_failed", etc.
    title = Column(String(255), nullable=False)
    message = Column(Text)
    
    data = Column(JSON)  # {analysis_id: 123, task_id: 456}
    is_read = Column(Boolean, default=False)
    
    created_at = Column(TIMESTAMP, server_default=func.now())
    read_at = Column(TIMESTAMP)
    
'''