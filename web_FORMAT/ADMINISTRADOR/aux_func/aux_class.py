from pydantic import BaseModel

class AdminResponse(BaseModel):
    id: int
    username: str
    role: str