from sqlalchemy import Column, Integer, String
from database import Base_BBDD

class Task(Base_BBDD):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String)
    project_id = Column(String)
    status = Column(String)
    progress = Column(Integer)
