from pydantic import BaseModel, EmailStr
from typing import Optional

class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    phone: str
    first_name: str
    last_name: str
    role: str

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    phone: str
    first_name: str
    last_name: str

class UserUpdate(BaseModel):
    first_name: str
    last_name: str
    phone: str
    new_password: Optional[str] = None
    confirm_password: Optional[str] = None
    role: Optional[str] = None
