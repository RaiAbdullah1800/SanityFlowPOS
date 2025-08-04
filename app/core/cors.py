from fastapi.middleware.cors import CORSMiddleware

def setup_cors(app):
    """
    Configure CORS middleware for the FastAPI application.
    
    Args:
        app: FastAPI application instance
        
    Returns:
        FastAPI: The configured FastAPI application
    """
    # List of allowed origins (you can customize this list as needed)
    allowed_origins = ["*"]
    
    # List of allowed methods
    allowed_methods = ["*"]  # Allow all methods
    
    # List of allowed headers
    allowed_headers = ["*"]  # Allow all headers
    
    # Add CORS middleware to the FastAPI application
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=allowed_methods,
        allow_headers=allowed_headers,
    )
    
    return app
