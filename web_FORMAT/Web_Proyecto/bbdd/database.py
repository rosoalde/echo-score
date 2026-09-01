from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

# Aquí defines la DB ya cargada, con host según entorno
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://webuser:webpass@db:5431/webdb")

# Engine global
engine = create_engine(DATABASE_URL)

# Session maker global
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para modelos
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
