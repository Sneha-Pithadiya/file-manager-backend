from app import models
from datetime import datetime

def log_action(db, user_id: int, action: str, target_path: str):
    """
    Log any user action (upload, create, delete, rename, etc.)
    """
    log = models.ActionLog(
        user_id=user_id,
        action=action,
        target_path=target_path,
        timestamp=datetime.now()
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
