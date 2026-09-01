from typing import List
from pydantic import BaseModel


class FilterRequest(BaseModel):
    terms: List[str] = []      # Filtro Geográfico
    custom_topic: str = ""     # Filtro por Topic (Nuevo)