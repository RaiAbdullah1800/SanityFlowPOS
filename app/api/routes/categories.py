from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from sqlalchemy.sql import func
from app.db.db import get_db
from app.db.models import Category, Item
from app.api.schemas.category import (
    CategoryCreate, CategoryResponse, CategoryUpdate, CategoryWithItems
)
from app.core.security import validate_admin

router = APIRouter(prefix="/admin/categories", tags=["Admin - Categories"])

@router.post("/", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    category: CategoryCreate,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Create a new category.
    """
    # Check if category with this name already exists
    db_category = db.query(Category).filter(
        func.lower(Category.name) == func.lower(category.name)
    ).first()
    
    if db_category:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A category with this name already exists"
        )
    
    db_category = Category(**category.dict())
    db.add(db_category)
    db.commit()
    db.refresh(db_category)
    return db_category

@router.get("/", response_model=List[CategoryResponse])
def list_categories(
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    List all categories.
    """
    categories = db.query(Category).all()
    return categories

@router.get("/{category_id}", response_model=CategoryWithItems)
def get_category(
    category_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get a specific category by ID, including its items.
    """
    db_category = db.query(Category).filter(Category.id == category_id).first()
    if not db_category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    
    # Get items for this category
    items = db.query(Item).filter(Item.category_id == category_id).all()
    
    # Convert to dict to avoid SQLAlchemy serialization issues
    category_data = {
        **db_category.__dict__,
        "items": [
            {"id": item.id, "name": item.name, "created_at": item.created_at}
            for item in items
        ]
    }
    
    return category_data

@router.put("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: str,
    category: CategoryUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Update a category's details.
    """
    db_category = db.query(Category).filter(Category.id == category_id).first()
    if not db_category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )
    
    # Check if new name is already taken by another category
    if category.name and category.name.lower() != db_category.name.lower():
        existing_category = db.query(Category).filter(
            func.lower(Category.name) == func.lower(category.name),
            Category.id != category_id
        ).first()
        
        if existing_category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A category with this name already exists"
            )
    
    # Update fields
    for field, value in category.dict(exclude_unset=True).items():
        setattr(db_category, field, value)
    
    db.commit()
    db.refresh(db_category)
    return db_category
