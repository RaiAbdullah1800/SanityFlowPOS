import logging
import sys
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.db.db import engine
from app.db import models
from app.core.logging import get_logger
from app.core.cors import setup_cors
from app.api.api import include_routers

# For exceptions
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

# Create tables
models.Base.metadata.create_all(bind=engine)

# Initialize root logger
logger = get_logger("app")

app = FastAPI(title="SanityFlow POS", version="1.0.0")

# Add startup event
@app.on_event("startup")
async def startup_event():
    """Log application startup"""
    logger.info("Application starting...")

# Add shutdown event
@app.on_event("shutdown")
def shutdown_event():
    """Log application shutdown"""
    logger.info("Application shutting down...")

# Setup CORS
app = setup_cors(app)

# Include all API routers
app = include_routers(app)

@app.get("/")
async def root():
    """Root endpoint that logs the access"""
    logger.info("Root endpoint accessed")
    return {"message": "SanityFlow POS API is live!"}



# Global exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions"""
    logger.error(f"HTTP error: {exc.detail}", exc_info=exc)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers if hasattr(exc, "headers") else None,
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors"""
    logger.error(f"Request validation error: {exc.errors()}", exc_info=exc)
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )

@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    """Handle Pydantic validation errors"""
    logger.error(f"Pydantic validation error: {str(exc)}", exc_info=exc)
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all other exceptions"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
