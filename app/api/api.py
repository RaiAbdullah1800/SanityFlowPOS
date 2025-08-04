from fastapi import APIRouter
from app.api.routes import (
    auth,
    admin,
    categories,
    cashier,
    cashier_dashboard,
    shared,
    admin_dashboard
)

def include_routers(app):
    """
    Include all API routers in the FastAPI application.
    
    Args:
        app: FastAPI application instance
        
    Returns:
        FastAPI: The configured FastAPI application
    """
    # Include all routers
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(categories.router)
    app.include_router(cashier.router)
    app.include_router(cashier_dashboard.router)
    app.include_router(shared.router)
    app.include_router(admin_dashboard.router)
    
    return app