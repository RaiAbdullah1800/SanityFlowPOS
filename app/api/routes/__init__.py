from . import auth, admin, categories, shared

__all__ = ["auth", "admin", "categories", "shared"]

routers = [
    auth.router,
    admin.router,
    categories.router,
    shared.router,
]
