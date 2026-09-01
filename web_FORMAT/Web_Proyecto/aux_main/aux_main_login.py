
from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta, timezone
from typing import Optional
import os
from bbdd.querys.general_querys import obtener_usuario_bbdd, verificar_user_bbdd
from bbdd.response.user_response import UserResponse
import hashlib

from bbdd.database import SessionLocal
from seguridad.audit_service import AuditService, EventType, EventResult, ActorType, get_request_context
##
#
#   Pipeline: Usuario no logueado -> es redirigido a loguearse -> main.js completa formulario logueo ->
#               main_FORMAT.login lo recoge -> aux_main.login_user lo recoge y verifica y el user -> bbdd
#               bbdd devuelve el user -> aux_main.login_user crea token y devuelve datos de user ->
#               main_FORMAT.login    devuelve token y datos user -> main.js guarda en cookies el token + user
#
##


ALGORITHM = "HS256"
SECRET_KEY = "ServidorEncriptandoUwU"
#SECRET_KEY =  os.getenv("SECRET_KEY")  #Poner este linea en lugar de la otra. La contraseña estará más segura
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)


'''
Esta función es para crear un token de usuario al loguear un usuario.
Este token es devuelto al frontend del usuario, y lo usará como DNI para identificarse al backend
'''

def _log_security_event(request: Request, event_type: EventType, message: str, actor_id=None, details: dict | None = None):
    """Auditoría puntual para casos anómalos detectados en get_current_user."""
    ctx = get_request_context(request)  # es una función normal, se puede llamar directo sin Depends
    db = SessionLocal()
    try:
        AuditService.log(
            db, event_type, result=EventResult.WARNING,
            message=message,
            actor_type=ActorType.USER, actor_id=actor_id,
            details=details or {},
            **ctx,
        )
    finally:
        db.close()
        
def create_access_token(user_id: int):
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=300)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def aux_login_post(username:str, password:str, log_ctx):
    #Si existe, debe devolver el id del user; sino nada
    user_exist = verificar_user_bbdd(username, password, log_ctx)
    
    if not user_exist:
        return None

    user = obtener_usuario_bbdd(user_exist)

    token = create_access_token(user.id)

    return token
    '''
    return {
        "access_token": token,
        "token_type": "bearer",        
    }
    '''
'''    return {
        "access_token": token,
        "token_type": "bearer",
            "user": {
                    "id": user.id,
                    "username": user.username,
                    "nombre": user.nombre,
                    "apellidos": user.apellidos,
                    "telefono": user.telefono,
                    "email": user.email
                    }
    }'''

def get_current_user(request: Request) -> UserResponse:
    token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except JWTError:
        # token inválido en general
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        _log_security_event(
            request, EventType.INVALID_TOKEN,
            message="Token JWT inválido o manipulado",
            details={"token_hash": token_hash},
        )
        raise HTTPException(status_code=401, detail="Token inválido")

    user = obtener_usuario_bbdd(user_id)

    if not user:
        _log_security_event(
            request, EventType.ACCESS_DENIED,
            message=f"Token válido pero el usuario '{user_id}' no existe",
            actor_id=int(user_id) if str(user_id).isdigit() else None,
        )
        raise HTTPException(401, "Usuario no encontrado")

    return user

def get_current_user_optional(request: Request) -> Optional[UserResponse]:

    token = request.cookies.get("access_token")

    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        return None

    user = obtener_usuario_bbdd(user_id)
    return user




def get_current_user_oauth2(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(401, "Token inválido")

    user = obtener_usuario_bbdd(user_id)

    if not user:
        raise HTTPException(401, "Usuario no encontrado")

    return user



def get_current_user_optional_oauth2(token: str = Depends(oauth2_scheme)) -> Optional[UserResponse]:

    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        return None

    user = obtener_usuario_bbdd(user_id)
    return user


