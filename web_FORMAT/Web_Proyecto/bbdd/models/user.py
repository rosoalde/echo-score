from sqlalchemy import Column, Integer, String, Boolean
from bbdd.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, nullable=False, unique=True, index=True)
    username = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=False, unique=True, index=True)
    phone = Column(String)
    hashed_password = Column(String, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String)
    role = Column(String)  # admin | analista | user
    is_active = Column(Boolean, server_default='TRUE')

