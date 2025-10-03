from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class UserCreate(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None

class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None 

class FolderResponse(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    created_at: datetime
    children: Optional[List["FolderResponse"]] = None  

    class Config:
        orm_mode = True

FolderResponse.update_forward_refs()

class UserOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime]

    class Config:
        orm_mode = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    username: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str
