from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.db import get_db
from app.db.models import User
from app.core.security import (
    hash_password, 
    verify_password, 
    create_access_token,
    create_refresh_token,
    verify_token,
    refresh_access_token
)
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/auth", tags=["Auth"])

class SignupRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = "cashier"

class LoginRequest(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

@router.post("/signup", response_model=Token)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    new_user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role
    )
    db.add(new_user)
    db.commit()
    
    # Generate tokens
    access_token = create_access_token({"sub": new_user.username, "scope": [new_user.role]})
    refresh_token = create_refresh_token({"sub": new_user.username, "scope": [new_user.role]})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token({"sub": user.username, "scope": [user.role]})
    refresh_token = create_refresh_token({"sub": user.username, "scope": [user.role]})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/refresh", response_model=Token)
def refresh_tokens(
    refresh_token: str,
    db: Session = Depends(get_db)
):
    try:
        # Verify refresh token
        payload = verify_token(refresh_token, "refresh")
        username = payload.get("sub")
        
        # Get user from database
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Generate new tokens
        access_token = create_access_token({"sub": user.username, "scope": [user.role]})
        new_refresh_token = create_refresh_token({"sub": user.username, "scope": [user.role]})
        
        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer"
        }
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    db.refresh(new_user)
    
    token = create_access_token({"sub": new_user.id})
    return {"access_token": token, "token_type": "bearer"}

@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_access_token({"sub": user.id})
    return {"access_token": token, "token_type": "bearer"}

@router.post("/logout")
def logout():
    # Client should discard the token — this is just a placeholder.
    return {"message": "Logged out. Just toss your token on client side."}
