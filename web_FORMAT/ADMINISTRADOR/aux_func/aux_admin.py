from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from aux_func.aux_class import AdminResponse
from typing import Optional

from dotenv import load_dotenv
import os
from datetime import datetime, timedelta, timezone


load_dotenv("/ADMINISTRADOR/config/.env")

ALGORITHM = "HS256"
SECRET_KEY =  os.getenv("SECRET_KEY")  #Poner este linea en lugar de la otra. La contraseña estará más segura
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

def create_access_token(user_id: int):
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=300)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def get_current_admin(request: Request) -> AdminResponse:
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
        raise HTTPException(status_code=401, detail="Token inválido")

    admin = obtener_usuario_admin(user_id)

    if not admin:
        raise HTTPException(401, "Usuario no encontrado")

    return admin


def get_current_admin_optional(request: Request) -> Optional[AdminResponse]:

    token = request.cookies.get("access_token")

    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError:
        return None

    user = obtener_usuario_admin(user_id)
    return user




def obtener_usuario_admin(user_id:int) -> AdminResponse | None:

    real_admin_id = os.getenv("ADMIN_ID")
    active = int(os.getenv("ADMIN_ACTIVE"))
    if user_id == real_admin_id and active == 1:
        return _admin_to_response()
    else:
        return None


def _admin_to_response() -> AdminResponse:
    """SALIDA"""
    # Obtener el primer rol del usuario, o 'viewer' por defecto

    return AdminResponse(
        id=os.getenv("ADMIN_ID"),
        username=os.getenv("ADMIN_USERNAME"),
        role=os.getenv("ADMIN_ROLE"),
    )

def verificar_admin(username:str, password:str):

    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    if(username != os.getenv("ADMIN_USERNAME")):
        return None
    
    if (not pwd_context.verify(password, str(os.getenv("ADMIN_PASS")))):
        return None
    
    return os.getenv("ADMIN_ID")

def aux_login_post(username:str, password:str):
    
    user_exist = verificar_admin(username, password)

    if not user_exist:
        return None

    user = obtener_usuario_admin(user_exist)
    
    token = create_access_token(user.id)

    return token