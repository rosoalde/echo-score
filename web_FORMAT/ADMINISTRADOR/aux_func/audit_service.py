"""
Servicio de auditoría.

Un solo punto de escritura (AuditService.log) en vez de una función por
evento -- añadir un evento nuevo es añadir un valor al Enum, no una función.

Este archivo se necesita duplicado en los dos codebases que escriben
auditoría (Web_Proyecto y ADMINISTRADOR), igual que ya haces con otros
aux_*, porque no comparten volumen. Ambos escriben en la misma tabla
`audit_logs` de la misma BBDD, así que no hay problema de consistencia,
solo de "tener el archivo copiado en los dos sitios".
"""

from __future__ import annotations

import enum
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from bbdd.models_all import AuditLog


# =========================
# OFFLOAD DE PAYLOADS "GORDOS" A FICHERO
# =========================
#
# Volumen dedicado, compartido entre Web_Proyecto/worker y ADMINISTRADOR
# (ver docker-compose.yml -> volumen "audit_blobs"). Solo vive aquí lo que
# no cabe cómodamente en la fila de la BBDD.

AUDIT_BLOBS_DIR = Path(os.getenv("AUDIT_BLOBS_DIR", "/audit_blobs"))
INLINE_DETAILS_MAX_BYTES = int(os.getenv("AUDIT_INLINE_MAX_BYTES", "2048"))  # ~2KB


def _offload_details(details: dict, category: str) -> tuple[dict, Optional[str], Optional[int]]:
    """
    Si el payload es pequeño, se queda tal cual (va en la columna JSON).
    Si es "gordo", se escribe en fichero y en la BBDD solo queda un resumen
    + la ruta relativa dentro de AUDIT_BLOBS_DIR.

    Devuelve: (details_para_guardar_en_bbdd, attachment_path, size_bytes)
    """
    if not details:
        return {}, None, None

    raw = json.dumps(details, ensure_ascii=False, default=str)
    size = len(raw.encode("utf-8"))

    if size <= INLINE_DETAILS_MAX_BYTES:
        return details, None, None

    blob_id = uuid.uuid4().hex
    now = datetime.utcnow()
    rel_path = f"{category}/{now:%Y/%m}/{blob_id}.json"
    full_path = AUDIT_BLOBS_DIR / rel_path

    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(raw, encoding="utf-8")

    summary = {
        "_offloaded": True,
        "_preview_keys": list(details.keys())[:10],
    }

    return summary, rel_path, size


# =========================
# ENUMS
# =========================

class ActorType(str, enum.Enum):
    USER = "user"      # usuario de la tabla `users` (la web de cara al cliente)
    ADMIN = "admin"     # admin del panel (AdminResponse, no vive en `users`)
    SYSTEM = "system"    # acciones automáticas: Celery, cron, scripts...


class EventResult(str, enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    WARNING = "warning"


class EventCategory(str, enum.Enum):
    AUTH = "auth"
    USER = "user"
    PROJECT = "project"
    KEYWORDS = "keywords"
    ACEPTACION = "aceptacion"
    PERMISSIONS = "permissions"
    SECURITY = "security"
    SYSTEM = "system"


class EventType(str, enum.Enum):
    # Autenticación
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"

    # Usuarios
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    USER_ENABLED = "user_enabled"
    USER_DISABLED = "user_disabled"

    # Permisos
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"
    PERMISSIONS_CHANGED = "permissions_changed"

    # KEYWORDS
    KEYWORDS_GENERATED = "keywords_generated"
    
    # ACEPTACION del proyecto
    ACEPTACION_GENERATED = "aceptacion_generated"
    
    # Proyectos / análisis
    PROJECT_CREATED = "project_created"
    PROJECT_UPDATED = "project_updated"
    PROJECT_DELETED = "project_deleted"
    PROJECT_ARCHIVED = "project_archived"
    PROJECT_RESTORED = "project_restored"
    PROJECT_STOPPED = "project_stopped"

    # Seguridad
    ACCESS_DENIED = "access_denied"
    INVALID_TOKEN = "invalid_token"
    SESSION_EXPIRED = "session_expired"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"

    # Sistema
    CONFIG_CHANGED = "config_changed"
    BACKUP_CREATED = "backup_created"
    BACKUP_RESTORED = "backup_restored"
    LOGS_PURGED = "logs_purged"


# Único sitio donde se decide la categoría de cada evento.
# Si añades un EventType nuevo y olvidas mapearlo aquí, log() lanza un
# error claro en vez de guardar una categoría inconsistente en silencio.
EVENT_CATEGORY_MAP: dict[EventType, EventCategory] = {
    EventType.LOGIN_SUCCESS: EventCategory.AUTH,
    EventType.LOGIN_FAILED: EventCategory.AUTH,
    EventType.LOGOUT: EventCategory.AUTH,
    EventType.PASSWORD_CHANGED: EventCategory.AUTH,
    EventType.PASSWORD_RESET_REQUESTED: EventCategory.AUTH,
    EventType.PASSWORD_RESET_COMPLETED: EventCategory.AUTH,

    EventType.USER_CREATED: EventCategory.USER,
    EventType.USER_UPDATED: EventCategory.USER,
    EventType.USER_DELETED: EventCategory.USER,
    EventType.USER_ENABLED: EventCategory.USER,
    EventType.USER_DISABLED: EventCategory.USER,
    
    EventType.ROLE_ASSIGNED: EventCategory.PERMISSIONS,
    EventType.ROLE_REVOKED: EventCategory.PERMISSIONS,
    EventType.PERMISSIONS_CHANGED: EventCategory.PERMISSIONS,

    EventType.KEYWORDS_GENERATED: EventCategory.KEYWORDS,
    
    EventType.PROJECT_CREATED: EventCategory.PROJECT,
    EventType.PROJECT_UPDATED: EventCategory.PROJECT,
    EventType.PROJECT_DELETED: EventCategory.PROJECT,
    EventType.PROJECT_ARCHIVED: EventCategory.PROJECT,
    EventType.PROJECT_RESTORED: EventCategory.PROJECT,
    EventType.PROJECT_STOPPED: EventCategory.PROJECT,

    EventType.ACEPTACION_GENERATED: EventCategory.ACEPTACION,
        
    EventType.ACCESS_DENIED: EventCategory.SECURITY,
    EventType.INVALID_TOKEN: EventCategory.SECURITY,
    EventType.SESSION_EXPIRED: EventCategory.SECURITY,
    EventType.RATE_LIMIT_EXCEEDED: EventCategory.SECURITY,

    EventType.CONFIG_CHANGED: EventCategory.SYSTEM,
    EventType.BACKUP_CREATED: EventCategory.SYSTEM,
    EventType.BACKUP_RESTORED: EventCategory.SYSTEM,
    EventType.LOGS_PURGED: EventCategory.SYSTEM,
}


# =========================
# CONTEXTO DE REQUEST (IP / user-agent / request_id)
# =========================
#
# Dependencia de FastAPI: `ctx: dict = Depends(get_request_context)`.
# Evita pasar IP/user_agent a mano en cada endpoint (y olvidarlo en alguno).
# request_id permite correlacionar todos los audit logs de una misma petición.

def get_request_context(request: Request) -> dict:
    return {
        "ip_address":   request.client.host if request.client else None,
        "port_address": str(request.client.port) if request.client else None,
        "user_agent":   request.headers.get("user-agent"),
        "request_id":   request.headers.get("x-request-id") or str(uuid.uuid4()),
    }


# =========================
# SERVICIO
# =========================

class AuditService:

    @staticmethod
    def log(
        db: Session,
        event_type: EventType,
        message: str,
        result: EventResult = EventResult.SUCCESS,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: Optional[int] = None,
        actor_username: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[int] = None,
        target_label: Optional[str] = None,
        ip_address: Optional[str] = None,
        port_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> AuditLog:
        """Punto único de escritura de auditoría. Todo lo demás son atajos sobre este método."""

        category = EVENT_CATEGORY_MAP.get(event_type)
        if category is None:
            raise ValueError(f"EventType '{event_type}' no está mapeado en EVENT_CATEGORY_MAP")

        details_to_store, attachment_path, attachment_size = _offload_details(
            details or {}, category.value
        )

        entry = AuditLog(
            event_type=event_type.value,
            category=category.value,
            result=result.value,
            actor_type=actor_type.value,
            actor_id=actor_id,
            actor_username=actor_username,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            ip_address=ip_address,
            port_address=port_address,
            user_agent=user_agent,
            session_id=session_id,
            request_id=request_id,
            message=message,
            details=details_to_store,
            attachment_path=attachment_path,
            attachment_size=attachment_size,
        )

        db.add(entry)
        db.commit()
        db.refresh(entry)

        return entry

    @staticmethod
    def get_full_details(entry: AuditLog) -> dict:
        """Devuelve los details completos, leyendo del fichero si se hizo offload."""
        if not entry.attachment_path:
            return entry.details or {}

        full_path = AUDIT_BLOBS_DIR / entry.attachment_path
        try:
            return json.loads(full_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"_error": "El fichero de detalle ya no existe (¿se purgó?)."}

    @staticmethod
    def purge_old_blobs(db: Session, days: int = 180) -> int:
        """
        Borra SOLO los ficheros de payload pesado más antiguos que `days`.
        La fila de auditoría (quién/qué/cuándo) se queda para siempre;
        solo se libera el espacio del contenido pesado.
        """
        threshold = datetime.utcnow() - timedelta(days=days)

        rows = (
            db.query(AuditLog)
            .filter(AuditLog.attachment_path.isnot(None))
            .filter(AuditLog.created_at < threshold)
            .all()
        )

        deleted = 0
        for row in rows:
            full_path = AUDIT_BLOBS_DIR / row.attachment_path
            try:
                full_path.unlink(missing_ok=True)
                deleted += 1
            except Exception:
                pass

            row.attachment_path = None
            row.attachment_size = None
            row.details = {"_purged": True, "_purged_at": datetime.utcnow().isoformat()}

        db.commit()
        return deleted

    # ---- atajos legibles para los eventos más comunes ----
    # Todos delegan en log(); son opcionales, solo para que el punto de
    # llamada quede más claro. Para un evento nuevo NO hace falta añadir
    # un atajo: basta con llamar a AuditService.log(...) directamente.

    @staticmethod
    def login_success(db: Session, user_id: int, username: str, ctx: dict, session_id: str | None = None):
        return AuditService.log(
            db, EventType.LOGIN_SUCCESS,
            message=f"Inicio de sesión de @{username}",
            actor_type=ActorType.USER, actor_id=user_id, actor_username=username,
            session_id=session_id, **ctx,
        )

    @staticmethod
    def login_failed(db: Session, username_attempted: str, reason: str, ctx: dict):
        return AuditService.log(
            db, EventType.LOGIN_FAILED, result=EventResult.FAILURE,
            message=f"Intento de login fallido para '{username_attempted}': {reason}",
            actor_type=ActorType.USER, actor_username=username_attempted,
            details={"reason": reason}, **ctx,
        )

    @staticmethod
    def user_action(
        db: Session,
        event_type: EventType,
        user_id: int,
        username: str,
        message: str,
        ctx: dict,
        target_type: str | None = None,
        target_id: int | None = None,
        target_label: str | None = None,
        details: dict | None = None,
        result: EventResult = EventResult.SUCCESS,
    ):
        """Atajo genérico para acciones de un usuario normal de la web (no admin)."""
        return AuditService.log(
            db, event_type, message=message, result=result,
            actor_type=ActorType.USER, actor_id=user_id, actor_username=username,
            target_type=target_type, target_id=target_id, target_label=target_label,
            details=details, **ctx,
        )
    @staticmethod
    def admin_action(
        db: Session,
        event_type: EventType,
        admin_id: int,
        admin_username: str,
        message: str,
        ctx: dict,
        target_type: str | None = None,
        target_id: int | None = None,
        target_label: str | None = None,
        details: dict | None = None,
        result: EventResult = EventResult.SUCCESS,
    ):
        """Atajo genérico para CUALQUIER acción hecha desde el panel de administración."""
        return AuditService.log(
            db, event_type, message=message, result=result,
            actor_type=ActorType.ADMIN, actor_id=admin_id, actor_username=admin_username,
            target_type=target_type, target_id=target_id, target_label=target_label,
            details=details, **ctx,
        )