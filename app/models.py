from sqlalchemy import Column, ForeignKey, Integer, String, Boolean, DateTime, Float
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship
from pydantic import BaseModel
from datetime import datetime

class FolderCreate(BaseModel):
    name: str
    parent_id: int = None  
    
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now())



class FileModel(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String,  index=True, nullable=False)
    original_name = Column(String, nullable=False)
    path = Column(String)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"))
    uploaded_at = Column(DateTime(timezone=True), default=datetime.now())
    is_folder = Column(Boolean, default=False)  
    is_star = Column(Boolean, default=False)
    uploaded_by = relationship("User")
    downloads = relationship("DownloadLog", back_populates="file")
    logs = relationship("FileLog", back_populates="file")
    parent_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    parent = relationship(
        "FileModel",
        remote_side=[id],   
        backref="children",
        foreign_keys=[parent_id]
    )
    size = Column(Float, default=0)


class DownloadLog(Base):
    __tablename__ = "download_logs"
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    downloaded_at = Column(DateTime(timezone=True), default=datetime.now())

    file = relationship("FileModel", back_populates="downloads")
    user = relationship("User")


class FileLog(Base):
    __tablename__ = "file_logs"
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"))
    action = Column(String, nullable=False)  
    user_id = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime(timezone=True), default=datetime.now())

    file = relationship("FileModel", back_populates="logs")
    user = relationship("User")
    
class RecycleBin(Base):
    __tablename__ = "recycle_bin"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True, nullable=False)
    original_name = Column(String, nullable=False)
    deleted_by_id = Column(Integer, ForeignKey("users.id"))
    deleted_at = Column(DateTime(timezone=True), default=datetime.now)
    is_folder = Column(Boolean, default=False)
    parent_id = Column(Integer, nullable=True)  

    deleted_by = relationship("User")

# from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
# from sqlalchemy.orm import relationship
# from sqlalchemy.sql import func
# from app.database import Base
# from datetime import datetime


# class User(Base):
#     __tablename__ = "users"

#     id = Column(Integer, primary_key=True, index=True)
#     username = Column(String, unique=True, index=True, nullable=False)
#     full_name = Column(String, nullable=True)
#     hashed_password = Column(String, nullable=False)
#     is_active = Column(Boolean, default=True)
#     created_at = Column(DateTime(timezone=True), default=datetime.now)
    
#     logs = relationship("ActionLog", back_populates="user")


# class ActionLog(Base):
#     __tablename__ = "action_logs"

#     id = Column(Integer, primary_key=True, index=True)
#     user_id = Column(Integer, ForeignKey("users.id"))
#     action = Column(String, nullable=False)
#     target_path = Column(String, nullable=False)  # file or folder path
#     timestamp = Column(DateTime(timezone=True), default=datetime.now)

#     user = relationship("User", back_populates="logs")
