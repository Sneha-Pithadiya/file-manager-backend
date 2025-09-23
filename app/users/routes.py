# app/users/routes.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app import schemas, models
from app.database import get_db
from app.auth.utils import get_current_user

router = APIRouter()


@router.get("/me", response_model=schemas.UserOut, summary="Get current logged-in user")
def read_users_me(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.get("/", response_model=List[schemas.UserOut], summary="List all users (authenticated)")
def list_users(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    users = db.query(models.User).all()
    return users
