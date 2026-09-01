from bbdd.database import SessionLocal
from bbdd.models_all import User, Role
from bbdd.response.user_response import UserResponse
from seguridad.audit_service import AuditService, EventType, EventResult, ActorType

# Llamada internas - internas
def get_user_by_id(user_id: int) -> UserResponse | None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
        if not user:
            return None
        return _user_to_response(user)
    finally:
        db.close()

# De momento no llamada
def get_user_by_username(username: str) -> UserResponse | None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username, User.is_active == True).first()
        if not user:
            return None
        return _user_to_response(user)
    finally:
        db.close()

# Llamada interna - medio externa
def verificar_user_bbdd(username: str, password: str, log_ctx) -> int | None:
    """Devuelve el user_id si las credenciales son correctas, None si no."""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        
        # El usuario no existe
        if not user:
            AuditService.log(
                db, EventType.LOGIN_FAILED, result=EventResult.FAILURE,
                message=f"Intento de login con usuario inexistente: '{username}'",
                actor_type=ActorType.USER, actor_username=username, **log_ctx,
                details={"reason": "Usuario no existe"},
            )
            return None
        
        # El usuario existe, pero no está habilitado para usarlo
        if(user.is_active == False):
            AuditService.log(
                db, EventType.LOGIN_FAILED, result=EventResult.FAILURE,
                message=f"Intento de login de cuenta deshabilitada: @{username}",
                actor_type=ActorType.USER, actor_id=user.id, actor_username=username, **log_ctx,
                details={"reason": "cuenta deshabilitada"},
            )
            return None
        
        # El usuario existe, está habilitado, pero no coinciden las contraseñas
        if not pwd_context.verify(password, user.hashed_password):
            AuditService.log(
                db, EventType.LOGIN_FAILED, result=EventResult.FAILURE,
                message=f"Intento de login con contraseña incorrecta: @{username}",
                actor_type=ActorType.USER, actor_id=user.id, actor_username=username, **log_ctx,
                details={"reason": "contraseña incorrecta"},
            )
            return None
        
        # En caso contrario, reportar éxito del logueo
        AuditService.log(
            db, EventType.LOGIN_SUCCESS, result=EventResult.SUCCESS,
            message=f"Inicio de sesión de @{username}",
            actor_type=ActorType.USER, actor_id=user.id, actor_username=username, **log_ctx,
        )
        return user.id
    finally:
        db.close()


def obtener_usuario_bbdd(user_id) -> UserResponse | None:
    return get_user_by_id(user_id)


def _user_to_response(user: User) -> UserResponse:
    """Convierte un objeto User de SQLAlchemy a UserResponse."""
    # Obtener el primer rol del usuario, o 'viewer' por defecto
    role = user.roles[0].name if user.roles else "viewer"

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        phone="",           # si no tienes phone en el modelo, string vacío
        first_name=user.first_name,
        last_name=user.last_name or "",
        role=role,
    )