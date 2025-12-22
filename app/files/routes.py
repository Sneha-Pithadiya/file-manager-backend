import os
import shutil
import tempfile
import threading
from typing import List, Optional
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, null
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.utils import get_current_user, role_required
from app import models
from app.files import utils
from pydantic import BaseModel
from sqlalchemy.orm import joinedload
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time


from app.schemas import CopyRequest

router = APIRouter()
 
#uploads directory (it change as per client needs) 
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
    
#pydantic models for file folder creation
class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None

    model_config = {"from_attributes": True}
 
class FileCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    model_config = {"from_attributes": True}

# def sync_uploads_with_db(db: Session, base_path: Path = UPLOAD_DIR, parent_id: Optional[int] = None):
   
#     base_path.mkdir(parents=True, exist_ok=True)

#     existing_entries = {
#         entry.filename.lower(): entry
#         for entry in db.query(models.FileModel).filter_by(parent_id=parent_id).all()
#     }

#     current_fs_entries = {entry.name.lower() for entry in base_path.iterdir() if not entry.name.startswith(".") and not entry.name.endswith((".tmp", "~"))}

#     for name_lower, db_entry in existing_entries.items():
#         if name_lower not in current_fs_entries:
#             db.query(models.FileLog).filter(models.FileLog.file_id == db_entry.id).delete()
#             db.delete(db_entry)
#             db.commit()
#             print(f"Deleted from DB and logs: {db_entry.filename}")

#     for entry in base_path.iterdir():
#         if entry.name.startswith(".") or entry.name.endswith((".tmp", "~")):
#             continue

#         name_lower = entry.name.lower()

#         if name_lower in existing_entries:
#             existing_db_entry = existing_entries[name_lower]
#             if entry.is_file():
#                 new_size = entry.stat().st_size
#                 if existing_db_entry.size != new_size:
#                     existing_db_entry.size = new_size
#                     db.commit()
#             if entry.is_dir():
#                 sync_uploads_with_db(db, entry, existing_db_entry.id)
#             continue

#         relative_path = Path("uploads") / entry.relative_to(UPLOAD_DIR)
#         new_file = models.FileModel(
#             filename=entry.name,
#             path=str(relative_path).replace("\\", "/"),
#             is_folder=entry.is_dir(),
#             parent_id=parent_id,
#             uploaded_at=datetime.now(),
#             uploaded_by_id=None,
#             size=entry.stat().st_size if entry.is_file() else 0,
#             is_star=False,
#         )
#         db.add(new_file)
#         db.commit()
#         db.refresh(new_file)

#         if entry.is_dir():
#             sync_uploads_with_db(db, entry, new_file.id)

#         print(f"Adding to DB: {relative_path}")

# class UploadsEventHandler(FileSystemEventHandler):
    # def __init__(self, db_factory):
    #     self.db_factory = db_factory

    # def on_created(self, event):
    #     if getattr(event, "from_api", False):
    #         # Skip files created by API
    #         return

    #     if event.src_path.endswith((".tmp", "~")):
    #         return

    #     db = self.db_factory()
    #     try:
    #         sync_uploads_with_db(db)
    #     finally:
    #         db.close()

#this function start watcher if not in db than add that files/ folders to db
# def start_watcher(db_factory):
#     event_handler = UploadsEventHandler(db_factory)
#     observer = Observer()
#     observer.schedule(event_handler, str(UPLOAD_DIR), recursive=True)
#     observer.start()

#     try:
#         while True:
#             time.sleep(5)
#     except KeyboardInterrupt:
#         observer.stop()
#     observer.join()

#get full path
def get_full_path(file: models.FileModel) -> str:
    parts = []
    current = file
    while current:
        parts.insert(0, current.filename)
        current = current.parent
    return str(UPLOAD_DIR / Path(*parts))

def get_folder_full_path(folder: models.FileModel):
    """Return the full path on disk for a folder object."""
    parts = [folder.filename]
    parent = folder.parent
    while parent:
        parts.insert(0, parent.filename)
        parent = parent.parent
    return UPLOAD_DIR.joinpath(*parts)

#create folder
@router.post("/folder")
def create_folder(
    folder: FolderCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    existing = db.query(models.FileModel).filter(
        models.FileModel.filename == folder.name,
        models.FileModel.parent_id == folder.parent_id,
        models.FileModel.is_folder == True
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Folder already exists")

    if folder.parent_id:
        parent_folder = db.query(models.FileModel).filter(models.FileModel.id == folder.parent_id).first()
        if not parent_folder:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        # Ensure we get a Path object from the parent
        parent_path = Path(get_folder_full_path(parent_folder))
    else:
        parent_path = Path(UPLOAD_DIR)

    new_folder_path = parent_path / folder.name
    new_folder_path.mkdir(parents=True, exist_ok=True)

    new_folder = models.FileModel(
        filename=folder.name,
        # Standardize path with forward slashes using as_posix()
        path=new_folder_path.as_posix(), 
        uploaded_by_id=current_user.id,
        is_folder=True,
        parent_id=folder.parent_id
    )
    db.add(new_folder)
    db.commit()
    db.refresh(new_folder)

    utils.append_log(new_folder.id, f" created folder by ", username=current_user.username)
    db.add(models.FileLog(user_id=current_user.id, file_id=new_folder.id, action="Create"))
    db.commit()

    return {
        "id": new_folder.id,
        "name": new_folder.filename,
        "type": "folder",
        "path": new_folder.path,
        "uploaded_by": current_user.username
    }

# create_file
@router.post("/createfile")
def create_file(
    file: FileCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    actual_parent_id = file.parent_id if file.parent_id and file.parent_id != 0 else None

    existing = db.query(models.FileModel).filter(
        models.FileModel.filename == file.name,
        models.FileModel.parent_id == actual_parent_id,
        models.FileModel.is_folder == False
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="File already exists")

    if actual_parent_id:
        parent_folder = db.query(models.FileModel).filter(models.FileModel.id == actual_parent_id).first()
        if not parent_folder:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        parent_disk_path = Path(get_folder_full_path(parent_folder))
    else:
        parent_disk_path = Path(UPLOAD_DIR)

    # Create physical file
    new_file_disk_path = parent_disk_path / file.name
    new_file_disk_path.touch(exist_ok=True)

    new_file = models.FileModel(
        filename=file.name,
        # Standardize path with forward slashes using as_posix()
        path=new_file_disk_path.as_posix(), 
        uploaded_by_id=current_user.id,
        is_folder=False,
        parent_id=actual_parent_id,
    )
    
    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    utils.append_log(new_file.id, f" created file by ", username=current_user.username)
    db.add(models.FileLog(user_id=current_user.id, file_id=new_file.id, action="Create"))
    db.commit()

    return {
        "id": new_file.id,
        "name": new_file.filename,
        "path": new_file.path,
        "type": "file",
        "uploaded_by": current_user.username
    }
#get/folder 
@router.get("/folder/{folder_id}", summary="Get contents of a folder")
def get_folder_contents(
    folder_id: int = 0,  
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if folder_id == 0:
        items = db.query(models.FileModel).filter(models.FileModel.parent_id == None, ~func.coalesce(models.FileModel.path, "").ilike("%recyclebin%")).all()
    else:
        items = db.query(models.FileModel).filter(models.FileModel.parent_id == folder_id, ~func.coalesce(models.FileModel.path, "").ilike("%recyclebin%")).all()

    result = []
    for f in items:
        result.append({
    "id": f.id,
    "filename": f.filename,
    # "original_name": f.original_name,
    "is_folder": f.is_folder,        
    "type": "folder" if f.is_folder else "file",
    "uploaded_by": f.uploaded_by.username if f.uploaded_by else None,
    "uploaded_at": f.uploaded_at,
    "path": f.path
})

    return result

# upload file
@router.post("/upload")
async def upload_file_or_folder(
    uploaded_file: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    parent_id: int = Form(None),
    current_user: models.User = Depends(get_current_user),  
):  
    saved_items = []

    # Determine upload path
    if not parent_id or parent_id == 0:
        parent_id = None
        upload_path = UPLOAD_DIR
    else:
        parent_folder = db.query(models.FileModel).filter(models.FileModel.id == parent_id).first()
        if not parent_folder:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        upload_path = Path(parent_folder.path or (UPLOAD_DIR / parent_folder.filename))
    
    upload_path.mkdir(parents=True, exist_ok=True)

    for file in uploaded_file:
        existing_file = db.query(models.FileModel).filter(
            models.FileModel.filename == file.filename,
            models.FileModel.parent_id == parent_id,
            models.FileModel.is_folder == False
        ).first()
        if existing_file:
            raise HTTPException(
                status_code=400,
                detail=f"File '{file.filename}' already exists in this folder."
            )

        file_path = upload_path / file.filename
        with open(file_path, "wb") as f:
            f.write(await file.read())

        file_db = models.FileModel(
            filename=file.filename,
            path=file_path.as_posix(),  
            uploaded_by_id=current_user.id if current_user else None,
            is_folder=False,
            parent_id=parent_id,
            size=file_path.stat().st_size,
            is_star=False,
        )
        db.add(file_db)
        db.commit()
        db.refresh(file_db)

        utils.append_log(file_db.id, f"uploaded {file.filename} by", username=current_user.username if current_user else "anonymous")

        saved_items.append({
            "id": file_db.id,
            "name": file.filename,
            "type": "file",
            "size": file_db.size,
            "parent_id": parent_id
        })

    return {"uploaded": saved_items}

#get files with pagination
@router.get("/")    
def get_files(folder_id: Optional[int] = None, page: int = 1, limit: int = 10, db: Session = Depends(get_db)):
    query = db.query(models.FileModel)
    if folder_id is not None:
        query = query.filter(models.FileModel.parent_id == folder_id, ~models.FileModel.path.ilike("%RecycleBin%"))
    else:
        query = query.filter(models.FileModel.parent_id == None, ~models.FileModel.path.ilike("%RecycleBin%"))

    total = query.count()
    items = query.offset((page - 1) * limit).limit(limit).all()

    data = [
        {
            "path": f.path,
            "id": f.id,
            # "original_name": f.original_name,
            "filename": f.filename,
            "is_folder": f.is_folder,
            "uploaded_by": f.uploaded_by.username if f.uploaded_by else None,
            "uploaded_at": f.uploaded_at,
            "size": f.size,
            "path":f.path if f.path else str((UPLOAD_DIR / f.filename).relative_to(UPLOAD_DIR)),
        }
        for f in items
    ]

    return {
        "data": data,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }

#see logs
@router.get("/log/{file_id}", summary="Get logs for a file/folder")
def get_file_log(file_id: int):
    log_file = utils.get_log_path(file_id)
    print(f" Checking path for log id {file_id}: {log_file}")

    if not log_file.exists():
        print(" Log file missing:", log_file)
        raise HTTPException(404, "No logs")

    print(" Found log file, returning data...")
    return {"file_id": file_id, "logs": log_file.read_text().splitlines()}

#properties of file/folder
@router.get("/properties")
def file_os_properties(file_id: int, db: Session = Depends(get_db)):

    file = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()
    if not file:
        raise HTTPException(404, detail="File not found in database.")

    full_path = get_full_path(file) 
    path = Path(full_path) 
    
    if not path.exists():
        raise HTTPException(404, detail=f"Physical file/folder not found at: {full_path}")

    stats = path.stat()
    file_type = "folder" if path.is_dir() else (path.suffix[1:] if path.suffix else "unknown")
    file_size_mb = stats.st_size / 1024 / 1024
    
    
    return {
        "name": path.name,
        "type": file_type,
        "size": file_size_mb,
        "created_at": datetime.fromtimestamp(stats.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
        "modified_at": datetime.fromtimestamp(stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "accessed_at": datetime.fromtimestamp(stats.st_atime).strftime("%Y-%m-%d %H:%M:%S"),
        "absolute_path": str(path.resolve()),
        "is_readable": os.access(path, os.R_OK),
        "is_writable": os.access(path, os.W_OK),
        "is_executable": os.access(path, os.X_OK)
    }

#download logs
@router.get("/log/{file_id}/download", summary="Download logs as text")
def download_file_log(file_id: int):
    log_file = utils.get_log_path(file_id)
    if not log_file.exists():
        raise HTTPException(404, "Log file not found")
    return FileResponse(path=log_file, filename=f"file_{file_id}_log.txt")

#download files
@router.get("/download/{file_id}", summary="Download a file or folder")
def download_file_or_folder(
    file_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    file_db = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()
    if not file_db:
        raise HTTPException(404, "Not found")

    if file_db.is_folder:
        folder_path = utils.get_folder_full_path(file_db)
        if not folder_path.exists() or not folder_path.is_dir():
            raise HTTPException(404, "Folder not found")

        temp_dir = Path(tempfile.gettempdir())
        zip_base = temp_dir / f"{file_db.id}_{file_db.filename}"
        zip_path = shutil.make_archive(str(zip_base), "zip", str(folder_path))
        send_path = Path(zip_path)
        send_name = f"{file_db.filename}.zip"

        background_tasks.add_task(send_path.unlink, missing_ok=True)

    else:
        # File download
        file_path = Path(file_db.path)
        if not file_path.exists():
            # Try upload dir
            file_path = UPLOAD_DIR / file_db.filename
            if not file_path.exists():
                raise HTTPException(404, f"File '{file_db.filename}' not found")

        send_path = file_path
        send_name = file_db.filename

    # Log download
    file_log = models.FileLog(
        file_id=file_db.id,
        user_id=current_user.id,
        action="Download"
    )
    db.add(file_log)
    db.commit()

    utils.append_log(file_db.id, f"Downloaded by ", username=current_user.username)

    return FileResponse(
        path=send_path,
        filename=Path(send_name).name,
        background=background_tasks
    )

#move to recycle bin
def move_to_recycle_bin_db(file_db, current_user, db: Session):
    """
    Safely move a file/folder to RecycleBin recursively.
    """
    if "RecycleBin" in str(file_db.path):
        return

    for child in getattr(file_db, "children", []):
        move_to_recycle_bin_db(child, current_user, db)

    file_log = models.FileLog(
        file_id=file_db.id,
        user_id=current_user.id,
        action="Delete"
    )
    db.add(file_log)

    file_path = None
    if file_db.is_folder:
        file_path = utils.get_folder_full_path(file_db)
    elif file_db.path:
        file_path = Path(file_db.path)
    else:
        file_path = utils.UPLOAD_DIR / file_db.filename

    if not file_path.exists():
        print(f"Skipping missing file: {file_path}")
        return

    if file_db.parent_id:
        parent_folder_db = db.query(models.FileModel).get(file_db.parent_id)
        parent_folder = utils.get_folder_full_path(parent_folder_db)
    else:
        parent_folder = utils.UPLOAD_DIR

    recycle_bin_folder = parent_folder / "RecycleBin"
    recycle_bin_folder.mkdir(parents=True, exist_ok=True)

    dest_path = recycle_bin_folder / file_db.filename
    if dest_path.exists():
        dest_path = recycle_bin_folder / f"{file_db.id}_{file_db.filename}"

    if str(dest_path).startswith(str(file_path)):
        print(f" Skipping self-move: {file_path} → {dest_path}")
        return

    try:
        shutil.move(str(file_path), str(dest_path))
    except Exception as e:
        print(f"Error moving {file_path} → {dest_path}: {e}")
        return

    recycle_item = models.RecycleBin(
        filename=file_db.filename,
        # original_name=file_db.original_name,
        deleted_by_id=current_user.id,
        is_folder=file_db.is_folder,
        path=str(dest_path)
    )
    db.add(recycle_item)

    log_path = utils.get_log_path(file_db.id)
    if log_path.exists():
        removed_log_path = log_path.parent / f"removed_log_file_{file_db.id}.txt"
        try:
            shutil.move(str(log_path), str(removed_log_path))
        except Exception as e:
            print(f"Error moving log file: {e}")

    try:
        db.delete(file_db)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"DB delete error: {e}")

#delete file/folder (move to recycle bin)
@router.delete("/delete/{file_id}", summary="Delete a file or folder (Move to RecycleBin)")
def delete_file_or_folder_db(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file_db = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()
    if not file_db:
        raise HTTPException(404, "File/Folder not found")

    utils.append_log(
        file_db.id,
        f" deleted file {file_db.filename}  by",
        username=current_user.username
    )

    move_to_recycle_bin_db(file_db, current_user, db)

    db.commit()

    return {"deleted_file_id": file_id, "status": "Moved to RecycleBin"}

#permanent delete from recycle bin
@router.delete("/permenent_delete/{recycle_id}", summary="Permanently delete a file/ folder from Recycle BIn")
def permanently_delete_from_recycle_bin_db(
    recycle_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(role_required("admin")), 
):
    recycle_item = db.query(models.RecycleBin).filter(models.RecycleBin.id == recycle_id).first()
        
    if not recycle_item:
        raise HTTPException(404, "RecycleBin item not found")

    src_path = Path(recycle_item.path)
    if src_path.exists():
        try:
            if recycle_item.is_folder:
                shutil.rmtree(src_path)
            else:
                src_path.unlink()
        except Exception as e:
            raise HTTPException(500, f"Error deleting file/folder: {e}")

    db.delete(recycle_item)
    db.commit()
    
    utils.append_log(
        recycle_item.id,
        f" permanently deleted from RecycleBin by",
        username=current_user.username
    )

    return {"status": "Permanently deleted"}

def generate_unique_filename(filename: str, existing_names: set) -> str:
    if filename not in existing_names:
        return filename
    
    name, ext = os.path.splitext(filename)
    counter = 1
    new_name = filename
    while new_name in existing_names:
        new_name = f"{name}_copy{counter}{ext}"
        counter += 1
    return new_name

def recursive_copy(src_record, dest_folder_id, db: Session, current_user):
    """
    src_record: The FileModel object we are copying
    dest_folder_id: The ID of the parent we are pasting into
    """
    if dest_folder_id:
        dest_parent = db.query(models.FileModel).filter(models.FileModel.id == dest_folder_id).first()
        dest_parent_path = Path(dest_parent.path)
    else:
        dest_parent_path = Path(UPLOAD_DIR)

    dest_parent_path.mkdir(parents=True, exist_ok=True)

    # 2. Prevent name collisions in the destination
    existing_names = {f.name for f in dest_parent_path.iterdir()}
    new_filename = generate_unique_filename(src_record.filename, existing_names)
    new_physical_path = dest_parent_path / new_filename

    # 3. Create DB Record
    new_record = models.FileModel(
        filename=new_filename,
        path=new_physical_path.as_posix(), # ✅ Standard POSIX path
        is_folder=src_record.is_folder,
        parent_id=dest_folder_id,
        uploaded_by_id=current_user.id,
        size=src_record.size if not src_record.is_folder else 0
    )
    db.add(new_record)
    db.flush() # Get new_record.id for children

    # 4. Physical Operation
    src_physical_path = Path(src_record.path)
    
    if src_record.is_folder:
        new_physical_path.mkdir(exist_ok=True)
        # Recursively copy children from the DB relationship
        for child in src_record.children:
            recursive_copy(child, new_record.id, db, current_user)
    else:
        if src_physical_path.exists():
            shutil.copy2(src_physical_path, new_physical_path)
            new_record.size = new_physical_path.stat().st_size
        else:
            print(f"Warning: Physical file {src_physical_path} missing during copy.")

    db.commit()
    return new_record

# copy_file_or_folder
def copy_file_or_folder(src: models.FileModel, dest_folder: models.FileModel, db: Session, current_user: models.User):

    src_path = UPLOAD_DIR / src.filename
    dest_path = UPLOAD_DIR / dest_folder.filename / src.filename if dest_folder else UPLOAD_DIR / src.filename
    
    if dest_path.exists():
         pass 

    if src.is_folder:
        shutil.copytree(src_path, dest_path)
    else:
        shutil.copy2(src_path, dest_path)

    new_file = models.FileModel(
        filename=src.filename,
        uploaded_by_id=current_user.id,
        is_folder=src.is_folder,
        parent_id=dest_folder.id if dest_folder else None,
    )
    db.add(new_file)
    db.commit()
    db.refresh(new_file)
    
    utils.append_log(new_file.id, f"Copied file {new_file.filename} using utility.", username=current_user.username)
    
    return new_file

@router.post("/copy")
def copy_files(
    request: CopyRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    dest_id = request.destination_folder_id if request.destination_folder_id != 0 else None
    
    copied_items = []
    for file_id in request.file_ids:
        # Load with children to ensure recursive copy works
        src_file = db.query(models.FileModel).options(joinedload(models.FileModel.children)).filter(
            models.FileModel.id == file_id
        ).first()
        
        if not src_file: continue

        try:
            new_record = recursive_copy(src_file, dest_id, db, current_user)
            copied_items.append({"id": new_record.id, "name": new_record.filename})
        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"Copy failed for {src_file.filename}: {str(e)}")

    return {"status": "success", "copied_files": copied_items}

@router.post("/move")
def move_files(
    request: CopyRequest, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # 1. Get Destination
    dest_folder = None
    if request.destination_folder_id and request.destination_folder_id != 0:
        dest_folder = db.query(models.FileModel).filter(
            models.FileModel.id == request.destination_folder_id,
            models.FileModel.is_folder == True
        ).first()
        dest_path_obj = Path(dest_folder.path)
    else:
        dest_path_obj = Path(UPLOAD_DIR)

    moved_files = []

    for file_id in request.file_ids:
        src_file = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()
        if not src_file: continue

        src_path = Path(src_file.path)
        
        # Determine initial target path
        target_path = dest_path_obj / src_file.filename

        if not src_path.exists():
            raise HTTPException(404, f"Source '{src_file.path}' not found on disk")

        # Check: Cannot move a folder into itself
        if src_file.is_folder and dest_path_obj.resolve().is_relative_to(src_path.resolve()):
            raise HTTPException(400, "Cannot move a folder into its own subfolder")

        try:
            # Handle name collisions at destination
            existing_names = {f.name for f in dest_path_obj.iterdir()}
            final_name = generate_unique_filename(src_file.filename, existing_names)
            final_dest_path = dest_path_obj / final_name

            # Physical Move
            shutil.move(str(src_path), str(final_dest_path))

            # Update DB Record
            src_file.filename = final_name
            src_file.path = final_dest_path.as_posix()
            src_file.parent_id = dest_folder.id if dest_folder else None

            if src_file.is_folder:
                update_child_paths(src_file, db)

            db.commit()
            moved_files.append({"id": src_file.id, "name": src_file.filename})

        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"Error moving {src_file.filename}: {str(e)}")

    return {"status": "success", "moved_files": moved_files}

def update_child_paths(parent_record, db):
    for child in parent_record.children:
        new_child_path = Path(parent_record.path) / child.filename
        child.path = new_child_path.as_posix()
        if child.is_folder:
            update_child_paths(child, db)
#rename file/folder
@router.put("/rename")
def rename_file_or_folder(
    file_id: int,
    new_name: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file = db.query(models.FileModel).filter_by(id=file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File/folder not found")

    final_name = new_name
    if not file.is_folder:
        _, old_ext = os.path.splitext(file.filename)
        _, new_ext = os.path.splitext(new_name)
        
        if not new_ext and old_ext:
            final_name = f"{new_name}{old_ext}"

    old_db_path = file.path.replace("\\", "/")
    old_path_obj = Path(old_db_path)
    
    new_db_path = (old_path_obj.parent / final_name).as_posix()
    
    old_full_disk_path = Path(UPLOAD_DIR).parent / old_db_path
    new_full_disk_path = Path(UPLOAD_DIR).parent / new_db_path

    if new_full_disk_path.exists():
        raise HTTPException(status_code=400, detail="A file or folder with this name already exists")

    try:
        if old_full_disk_path.exists():
            old_full_disk_path.rename(new_full_disk_path)

        file.filename = final_name
        file.path = new_db_path

        if file.is_folder:
            old_prefix = old_db_path if old_db_path.endswith('/') else f"{old_db_path}/"
            new_prefix = new_db_path if new_db_path.endswith('/') else f"{new_db_path}/"

            children = (
                db.query(models.FileModel)
                .filter(models.FileModel.path.like(f"{old_prefix}%") | 
                        models.FileModel.path.like(f"{old_prefix.replace('/', '\\')}%"))
                .all()
            )

            for child in children:
                current_child_path = child.path.replace("\\", "/")
                child.path = current_child_path.replace(old_prefix, new_prefix, 1)

        db.commit()
        return {"message": "Successfully Renamed", "new_name": final_name, "new_path": new_db_path}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Rename failed: {str(e)}")

#star
@router.put("/star")
def star_file_or_folder(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    file = db.query(models.FileModel).filter(models.FileModel.id == file_id).first()

    if not file:
        raise HTTPException(status_code=404, detail="File/folder not found")

    try:
        file.is_star = not file.is_star

        db.add(file)
        db.commit()
        db.refresh(file)

        utils.append_log(file.id, f"{current_user.username} toggled star for '{file.filename}'")
        return {
            "id": file.id,
            "is_star": file.is_star,
            "filename": file.filename,
            "message": f"File {'starred' if file.is_star else 'unstarred'} successfully"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# search
@router.get("/search/{query}")
def search_file(query: str, db: Session = Depends(get_db)):
    """
    Search for files anywhere in folders or subfolders
    """
    search_term = f"%{query}%"  

    files = db.query(models.FileModel).filter(
        models.FileModel.filename.like(search_term), ~models.FileModel.path.ilike("%RecycleBin%")
    ).all()

    return {"results": files}


@router.post("/sync-disk-to-db")
def sync_disk_to_db(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    upload_root = Path(UPLOAD_DIR) 
    
    db_files = {
        f.path.replace("\\", "/"): f
        for f in db.query(models.FileModel).all()
    }

    created_count = 0

    paths = sorted(upload_root.rglob("*"), key=lambda p: len(p.parts))

    for fs_path in paths:
        if fs_path.name.startswith(".") or fs_path.name == "uploads":
            continue

        relative_to_root = fs_path.relative_to(upload_root)
        db_path = utils.to_db_path(relative_to_root)

        if db_path in db_files:
            continue

        parent_db_path = utils.get_parent_db_path(db_path)
        parent_record = db_files.get(parent_db_path)

        new_record = models.FileModel(
            filename=fs_path.name,
            path=db_path,
            is_folder=fs_path.is_dir(),
            parent_id=parent_record.id if parent_record else None,
            uploaded_by_id=current_user.id,
            size=fs_path.stat().st_size if fs_path.is_file() else 0,
            is_star=False # Assuming default
        )

        db.add(new_record)
        
        try:
            db.flush() 
            db_files[db_path] = new_record 
            created_count += 1
        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"Error syncing {db_path}: {str(e)}")

    db.commit()

    return {
        "message": "Disk sync completed",
        "created_entries": created_count
    }

#recycle bin get
@router.get("/recyclebin")
def get_recyclebin(db:Session = Depends(get_db)):
    """
    get all files folder of recyclbin
    """
    items = db.query(models.RecycleBin).all()
    
        
    return {"results":items}    

RECYCLE_BIN_DIR = os.path.join(UPLOAD_DIR, "RecycleBin")

@router.post("/restore/{file_id}")
def restore_file(
    file_id: int,
    replace: bool = Query(False, description="Set to True to overwrite if file exists at destination."),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    recycle_file = db.query(models.RecycleBin).filter(models.RecycleBin.id == file_id).first()
    if not recycle_file:
        raise HTTPException(status_code=404, detail="File not found in Recycle Bin")

    src_path = Path(recycle_file.path)
    file_name = src_path.name

    # Logic to find the original parent: 
    # Usually, if you store in .recyclebin/filename, the original parent is the root or specific folder
    original_parent_disk_path = src_path.parent.parent

    # Standardize the search path to match your DB format (Posix)
    search_path = original_parent_disk_path.as_posix()

    # Find original parent folder in DB
    original_parent_db = db.query(models.FileModel).filter(
        models.FileModel.path == search_path
    ).first()

    if original_parent_db:
        target_folder_disk_path = original_parent_disk_path
        target_parent_id = original_parent_db.id  
    else:
        target_folder_disk_path = Path(UPLOAD_DIR)
        target_parent_id = None

    target_path = target_folder_disk_path / file_name

    # Handle Overwrite Logic
    if target_path.exists():
        if not replace:
            raise HTTPException(
                status_code=409,
                detail=f"File '{file_name}' already exists at destination."
            )
        else:
            # Important: search using .as_posix() to find the existing DB record
            old_file_db = db.query(models.FileModel).filter(
                models.FileModel.path == target_path.as_posix()
            ).first()
            
            if old_file_db:
                db.delete(old_file_db)
                db.commit()
            
            try:
                if target_path.is_file():
                    target_path.unlink()
                else:
                    shutil.rmtree(target_path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to delete existing file: {str(e)}")

    # Physical Move
    try:
        target_folder_disk_path.mkdir(parents=True, exist_ok=True)
        # Use .as_posix() or string conversion for shutil
        shutil.move(src_path.as_posix(), target_path.as_posix())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore file on disk: {str(e)}")

    # DB Update
    db.delete(recycle_file)  # remove from recycle bin
    
    restored_file = models.FileModel(
        filename=file_name,
        path=target_path.as_posix(),  
        uploaded_by_id=current_user.id,
        is_folder=recycle_file.is_folder,
        parent_id=target_parent_id,
    )
    db.add(restored_file)
    db.commit()
    db.refresh(restored_file)

    return {
        "status": "success",
        "message": f"File '{file_name}' restored successfully",
        "target_path": restored_file.path
    }