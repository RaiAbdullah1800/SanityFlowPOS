from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
import os
from typing import Optional

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("JWT_SECRET", "supersecret")  # fallback
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
REFRESH_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days

# Generate a random secret for refresh tokens
def generate_refresh_token_secret():
    return os.urandom(32).hex()

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    """Create a JWT access token with the given data"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "token_type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict, expires_delta: timedelta = None):
    """Create a JWT refresh token with the given data"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "token_type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str, token_type: str = "access"):
    """Verify a JWT token and return its payload"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("token_type") != token_type:
            raise JWTError("Invalid token type")
        return payload
    except JWTError as e:
        raise JWTError(f"Could not validate credentials: {str(e)}")

def refresh_access_token(refresh_token: str, user_id: str):
    """Generate a new access token using a valid refresh token"""
    try:
        payload = verify_token(refresh_token, "refresh")
        if payload.get("sub") != user_id:
            raise JWTError("Refresh token does not match user")
        
        # Create new access token
        return create_access_token({
            "sub": user_id,
            "scope": payload.get("scope", [])
        })
    except JWTError:
        raise JWTError("Invalid refresh token")
