from fastapi import APIRouter
from app.api.routes import (
    auth,
    admin,
    categories,
    cashier,
    cashier_dashboard,
    shared,
    admin_dashboard,
    shopper
)

api_router = APIRouter()

def include_routers(app):
    """
    Include all API routers in the FastAPI application.
    
    Args:
        app: FastAPI application instance
        
    Returns:
        FastAPI: The configured FastAPI application
    """
    # Include all routers
    api_router.include_router(auth.router)
    api_router.include_router(admin.router)
    api_router.include_router(cashier.router)
    api_router.include_router(categories.router)
    api_router.include_router(admin_dashboard.router)
    api_router.include_router(cashier_dashboard.router)
    api_router.include_router(shared.router)
    
    api_router.include_router(shopper.router, prefix="/shoppers", tags=["Shoppers"])
    app.include_router(api_router)
    
    return app