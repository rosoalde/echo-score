from sqlalchemy import Column, Integer, String, Text, ForeignKey, TIMESTAMP
from sqlalchemy.sql import func
from database import Base


class Analysis(Base):
    __tablename__ = "analysis"  # ✅ corregido

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("usuario.id"), nullable=False)

    project_name = Column(String(255), nullable=False, index=True)

    tema = Column(Text)

    output_folder = Column(Text)

    population_scope = Column(Text)

    keywords = Column(Text)

    status_id = Column(Integer, ForeignKey("status.id"))  # ✅ relación

    created_at = Column(TIMESTAMP, server_default=func.now())  # ✅ bien

