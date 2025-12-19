from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# --- USER SCHEMAS ---

class UserCreate(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None

class UserOut(BaseModel):
    id: int
    username: str
    full_name: Optional[str] = None
    is_active: bool
    role: str  #  ADDED: Role field
    created_at: Optional[datetime]

    class Config:
        orm_mode = True

class UserLogin(BaseModel):
    username: str
    password: str

# --- AUTH SCHEMAS ---

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None  


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


class CopyRequest(BaseModel):
    file_ids: List[int]
    destination_folder_id: Optional[int] = None

class MoveRequest(BaseModel): # Added for completeness of move/cut operation
    file_ids: List[int]
    destination_folder_id: Optional[int] = None
    
FolderResponse.update_forward_refs()