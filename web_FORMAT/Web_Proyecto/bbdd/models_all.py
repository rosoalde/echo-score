from sqlalchemy import (
    Column, Integer, String, Text, Boolean,
    ForeignKey, TIMESTAMP, Enum, JSON,
    CheckConstraint, BigInteger, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from bbdd.database import Base
import enum
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy import UniqueConstraint
import re


# =========================
# 🎯 ENUMS (Estados predefinidos)
# =========================
class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class TaskTypeEnum(str, enum.Enum):
    SCRAPING = "scraping"
    CLEANING = "cleaning"
    ANALYSIS_LLM = "analysis_llm"
    EXPORT = "export"
    NOTIFICATION = "notification"
    GENERATING_KW = "generating_keywords"
    CONFIGURATION = "configuration"
    SCOREOP = "scoreop"
    REPORTING = "reporting"

class AnalysisStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    ERROR = "error"
    CANCELLED = "cancelled"


# =========================
# USER
# =========================
class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(Text, nullable=False)

    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100))

    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    # relationships
    analyses = relationship("Analysis", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    tasks = relationship("AnalysisTask", back_populates="user", cascade="all, delete-orphan")

    roles = relationship("Role", secondary="user_roles", back_populates="users")

# =========================
# ROLE
# =========================
class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    permissions = Column(JSON, default=list)

    users = relationship("User", secondary="user_roles", back_populates="roles")

# =========================
# ROLES - USER
# =========================
class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)

# =========================
# USER SESSION
# =========================
class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)

    token_hash = Column(String(255), nullable=False, index=True)
    ip_address = Column(String(45))
    user_agent = Column(Text)

    expires_at = Column(TIMESTAMP, nullable=False, index=True)
    revoked = Column(Boolean, default=False)

    created_at = Column(TIMESTAMP, server_default=func.now())

    user = relationship("User", back_populates="sessions")


# =========================
# ANALYSIS
# =========================
class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    output_folder = Column(String(500), nullable=True)

    project_name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, index=True)

    status = Column(Enum(AnalysisStatus, native_enum=True), default=AnalysisStatus.DRAFT)

    progress_percent = Column(Integer, default=0)

    analysis_config = Column(MutableDict.as_mutable(JSON), default=dict)

    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="analyses")
    tasks = relationship("AnalysisTask", back_populates="analysis", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_analysis_user_slug"),
    )

# =========================
# TASK
# =========================
class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"

    id = Column(BigInteger, primary_key=True)

    # Ambos opcionales — uno u otro según el tipo de tarea
    analysis_id = Column(BigInteger, ForeignKey("analyses.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    celery_task_id = Column(String(100), nullable=True, index=True)
    
    task_type = Column(Enum(TaskTypeEnum, native_enum=True), nullable=False)
    status = Column(Enum(TaskStatus, native_enum=True), default=TaskStatus.PENDING)

    priority = Column(Integer, default=5)

    progress_percent = Column(Integer, default=0)
    total_items = Column(Integer)
    processed_items = Column(Integer, default=0)

    # Campos de seguimiento temporal — AÑADIR ESTOS
    current_step = Column(Text)
    started_at = Column(TIMESTAMP)
    queued_at = Column(TIMESTAMP)
    finished_at = Column(TIMESTAMP)

    message = Column(Text)
    error_message = Column(Text)

    created_at = Column(TIMESTAMP, server_default=func.now())

    input_config = Column(MutableDict.as_mutable(JSON), default=dict)
    output_summary = Column(MutableDict.as_mutable(JSON), default=dict)

    user = relationship("User", back_populates="tasks")
    analysis = relationship("Analysis", back_populates="tasks")
    logs = relationship("TaskLog", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "analysis_id IS NOT NULL OR user_id IS NOT NULL",
            name="check_task_has_scope"
        ),
        CheckConstraint(
            "total_items IS NULL OR processed_items <= total_items",
            name="check_processed_le_total"
        ),
        CheckConstraint(
            "progress_percent BETWEEN 0 AND 100",
            name="check_progress_range"
        ),
        Index("ix_tasks_user_status", "user_id", "status"),
        Index("ix_tasks_analysis_status", "analysis_id", "status"),
    )

# =========================
# LOGS
# =========================
class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True)
    task_id = Column(BigInteger, ForeignKey("analysis_tasks.id", ondelete="CASCADE"), index=True)

    level = Column(String(20), default="INFO")
    message = Column(Text, nullable=False)

    meta_data = Column(MutableDict.as_mutable(JSON), default=dict)

    created_at = Column(TIMESTAMP, server_default=func.now())

    task = relationship("AnalysisTask", back_populates="logs")


# =========================
# AUDIT LOG (auditoría de acciones, distinto de TaskLog)
# =========================
#
# TaskLog       -> ejecución de tareas de Celery (scraping, análisis...)
# AuditLog      -> quién hizo qué acción sensible, cuándo y desde dónde
#                  (login, CRUD de usuarios, permisos, proyectos, seguridad, sistema)
#
# No lleva FK a `users` a propósito: el actor puede ser un usuario normal,
# el admin del panel (que ni siquiera vive en la tabla `users`) o el propio
# sistema (Celery). Los datos del actor/target se guardan denormalizados
# para que el log sobreviva aunque se borre la fila original.

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True)

    # String, no Enum nativo de Postgres: se espera ir añadiendo tipos de
    # evento con frecuencia y así no hace falta migración por cada uno.
    event_type = Column(String(50), nullable=False, index=True)
    category = Column(String(30), nullable=False, index=True)
    result = Column(String(20), nullable=False, default="success", index=True)

    # quién hizo la acción
    actor_type = Column(String(20), nullable=False, index=True)   # user | admin | system
    actor_id = Column(BigInteger, nullable=True)
    actor_username = Column(String(150), nullable=True)

    # a quién/qué afecta (opcional): otro usuario, un proyecto, un rol...
    target_type = Column(String(30), nullable=True, index=True)
    target_id = Column(BigInteger, nullable=True, index=True)
    target_label = Column(String(150), nullable=True)

    ip_address = Column(String(45))
    port_address = Column(String(45))
    user_agent = Column(Text)
    session_id = Column(String(100), nullable=True)
    request_id = Column(String(100), nullable=True, index=True)

    message = Column(Text, nullable=False)
    details = Column(MutableDict.as_mutable(JSON), default=dict)

    # Si el payload de "details" era grande, se guarda en fichero aparte
    # (ver audit_service._offload_details) y aquí solo queda la referencia.
    attachment_path = Column(String(300), nullable=True)
    attachment_size = Column(Integer, nullable=True)  # bytes

    created_at = Column(TIMESTAMP, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_audit_actor", "actor_type", "actor_id"),
        Index("ix_audit_target", "target_type", "target_id"),
    )


# =========================
# SLUG
# =========================
import re
import unicodedata
import hashlib
import os
from sqlalchemy.orm import Session

def generate_slug2(name: str) -> str:
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')
    short_hash = hashlib.sha1(os.urandom(4)).hexdigest()[:6]
    return f"{slug}-{short_hash}"

import re
import unicodedata


def generate_slug_format(name: str) -> str:
    replacements = {
        # Español
        'ñ': 'ny',
        'Ñ': 'NY',

        # Valenciano / Catalán
        'ç': 'c',
        'Ç': 'C',
        'l·l': 'll',
        'L·L': 'LL',
        'L·l': 'Ll',
        'l·L': 'lL',
    }

    for old, new in replacements.items():
        name = name.replace(old, new)

    # Eliminar acentos
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')

    slug = name.lower()
    slug = re.sub(r'[^a-z0-9()_.\-]+', '-', slug).strip('-')

    return slug
    
def generate_slug(db: Session, name: str, username: str) -> str:

    try:
        list_projects = get_user_project_names(db, username)
        if name not in list_projects:
            return generate_slug_format(name)

        counter = 1
        while True:
            new_name = f"{name}({counter})"
            if new_name not in list_projects:
                return generate_slug_format(new_name)
            counter += 1
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

from sqlalchemy.orm import Session
from typing import List

def get_user_project_names(db: Session, username: str) -> List[str]:
    """
    Devuelve solo los nombres de los proyectos de un usuario dado por username.
    """
    project_names = (
        db.query(Analysis.project_name)
        .join(User)
        .filter(User.username == username)
        .order_by(Analysis.created_at.desc())
        .all()
    )
    # `all()` devuelve lista de tuplas, convertimos a lista de strings
    return [name[0] for name in project_names]