from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.db import get_db
from app.db.models import User, UserRole
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token,
    refresh_access_token,
)  # ensure these are defined in security.py

router = APIRouter(prefix="/auth", tags=["Auth"])

# --- Pydantic Schemas ---
class SignupRequest(BaseModel):
    username: str
    password: str
    role: UserRole = UserRole.cashier  # enforce valid enum

class LoginRequest(BaseModel):
    username: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

# --- Routes ---
@router.post("/signup", response_model=TokenResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    role_str = user.role.value
    access = create_access_token({"sub": user.username, "scope": [role_str]})
    refresh = create_refresh_token({"sub": user.username, "scope": [role_str]})
    return {"access_token": access, "refresh_token": refresh}

@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role_str = user.role.value
    access = create_access_token({"sub": user.username, "scope": [role_str]})
    refresh = create_refresh_token({"sub": user.username, "scope": [role_str]})
    return {"access_token": access, "refresh_token": refresh}

@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        token_data = verify_token(payload.refresh_token, "refresh")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = token_data.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_access = refresh_access_token(payload.refresh_token, user.username)
    role_str = user.role.value
    new_refresh = create_refresh_token({"sub": user.username, "scope": [role_str]})
    return {"access_token": new_access, "refresh_token": new_refresh}

@router.post("/logout")
def logout():
    # Token discard is client responsibility
    return {"message": "Logged out. Please discard tokens on client side."}
