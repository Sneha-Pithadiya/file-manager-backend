from typing import Optional
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import bcrypt
from app import models 
from app.database import get_db
from app.schemas import TokenData 
from app.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

#helping function for register / login
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode())

def get_password_hash(password: str) -> str:
    pw = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw, salt).decode()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta if expires_delta else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()


def authenticate_user(db: Session, username: str, password: str):
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

#current user
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    print("Token received:", token)
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials or token expired",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        print("Decoded payload:", payload)
        
        username: str = payload.get("sub")
        # role
        user_role: str = payload.get("role") 
        
        print("Username from token:", username)
        
        if username is None:
            raise credentials_exception
            
    except JWTError as e:
        print("JWT decode error:", e)
        raise credentials_exception
    
    user = get_user_by_username(db, username)
    print("User from DB:", user)
    
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user

# role
def role_required(required_role: str):
    """
    Dependency function to check if the current user has the required role.
    Assumes models.User has a 'role' attribute.
    """
    def role_checker(current_user: models.User = Depends(get_current_user)):
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User must have '{required_role}' role to access this resource."
            )
        return current_user
    return role_checker