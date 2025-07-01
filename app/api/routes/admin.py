from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict
from datetime import datetime
from pydantic import BaseModel, HttpUrl, conint, validator

from app.db.db import get_db
from app.db.models import (
    Item, ItemSize, InventoryHistory, InventoryChangeType,
    Order, OrderItem, User, UserRole
)
from app.core.security import validate_admin

router = APIRouter(prefix="/admin", tags=["Admin"])

# --- Pydantic Models ---
class ItemSizeCreate(BaseModel):
    size_label: str
    price: float
    discount: Optional[float] = None
    stock: conint(ge=0) = 0  # Initial stock, must be >= 0

class ItemCreate(BaseModel):
    name: str
    image_url: Optional[HttpUrl]
    category: str
    sizes: List[ItemSizeCreate]  # Now requires at least one size

class ItemSizeResponse(ItemSizeCreate):
    id: str
    item_id: str
    created_at: datetime

    class Config:
        orm_mode = True

class ItemResponse(BaseModel):
    id: str
    name: str
    image_url: Optional[HttpUrl]
    category: str
    created_at: datetime
    sizes: List[ItemSizeResponse]

    class Config:
        orm_mode = True

class ItemSizeUpdate(BaseModel):
    size_label: Optional[str]
    price: Optional[float]
    discount: Optional[float]

class ItemUpdateSize(BaseModel):
    id: Optional[str]  # If provided, update existing size. If None, create new size
    size_label: str
    price: float
    discount: Optional[float] = None
    stock: Optional[conint(ge=0)] = None  # Optional stock update, must be >= 0 if provided
    correction_reason: Optional[str] = None  # Required if stock is being changed

    @validator('correction_reason')
    def validate_correction_reason(cls, v, values):
        if 'stock' in values and values['stock'] is not None and not v:
            raise ValueError('correction_reason is required when updating stock')
        return v

class ItemUpdate(BaseModel):
    name: Optional[str]
    image_url: Optional[HttpUrl]
    category: Optional[str]
    sizes: List[ItemUpdateSize]  # Sizes to update or create
    sizes_to_delete: Optional[List[str]] = []  # List of size IDs to delete

class RestockRequest(BaseModel):
    item_id: str
    size_label: str
    quantity: conint(gt=0)  # Must be positive
    description: Optional[str]

class DateRangeFilter(BaseModel):
    start_date: Optional[datetime]
    end_date: Optional[datetime]

# --- Item Management ---
@router.post("/add-items/", status_code=status.HTTP_201_CREATED, response_model=ItemResponse)
async def add_item(
    item: ItemCreate,
    db: Session = Depends(get_db),
    token: dict = Depends(validate_admin)
):
    # Get the performing user
    username = token.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Performing user not found")

    # Create the item
    db_item = Item(
        name=item.name,
        image_url=item.image_url,
        category=item.category
    )
    db.add(db_item)
    db.flush()  # Flush to get the item ID but don't commit yet

    # Create all sizes for the item
    for size in item.sizes:
        db_size = ItemSize(
            item_id=db_item.id,
            size_label=size.size_label,
            price=size.price,
            discount=size.discount,
            stock=size.stock
        )
        db.add(db_size)

        # If initial stock is provided, create inventory history entry
        if size.stock > 0:
            history = InventoryHistory(
                item_id=db_item.id,
                change=size.stock,
                type=InventoryChangeType.restock,
                description="Initial stock",
                performed_by_id=user.id
            )
            db.add(history)

    # Now commit everything together
    db.commit()
    db.refresh(db_item)
    return db_item

@router.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """Get detailed information about a specific item including all its sizes"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@router.get("/items/", response_model=List[ItemResponse])
async def list_items(
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """Get a list of all items with their sizes"""
    items = db.query(Item).all()
    return items

@router.patch("/items/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: str,
    item_update: ItemUpdate,
    db: Session = Depends(get_db),
    token: dict = Depends(validate_admin)
):
    """Update an item's details, including its sizes. Can update item info, update existing sizes,
    add new sizes, and delete sizes all in one request. When updating stock, a correction reason
    must be provided to explain the adjustment."""
    
    # Get the performing user
    username = token.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Performing user not found")

    # First verify the item exists
    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Update basic item information
    if item_update.name is not None:
        db_item.name = item_update.name
    if item_update.image_url is not None:
        db_item.image_url = item_update.image_url
    if item_update.category is not None:
        db_item.category = item_update.category

    # Handle size updates and additions
    existing_sizes = {size.id: size for size in db_item.sizes}
    
    for size_update in item_update.sizes:
        if size_update.id:  # Update existing size
            if size_update.id not in existing_sizes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Size with id {size_update.id} not found for this item"
                )
            db_size = existing_sizes[size_update.id]
            
            # Calculate stock change if stock is being updated
            if size_update.stock is not None:
                stock_change = size_update.stock - db_size.stock
                if stock_change != 0:
                    # For large corrections (more than 20% change), add a warning to the description
                    stock_change_percentage = abs(stock_change) / db_size.stock * 100 if db_size.stock > 0 else 100
                    description = f"Correction: {size_update.correction_reason}"
                    if stock_change_percentage > 20:
                        description = f"LARGE ADJUSTMENT ({stock_change_percentage:.1f}% change) - {description}"

                    history = InventoryHistory(
                        item_id=item_id,
                        change=stock_change,
                        type=InventoryChangeType.correction,
                        description=description,
                        performed_by_id=user.id
                    )
                    db.add(history)
                db_size.stock = size_update.stock

            # Update other fields
            db_size.size_label = size_update.size_label
            db_size.price = size_update.price
            if size_update.discount is not None:
                db_size.discount = size_update.discount

        else:  # Add new size
            new_size = ItemSize(
                item_id=item_id,
                size_label=size_update.size_label,
                price=size_update.price,
                discount=size_update.discount,
                stock=size_update.stock or 0
            )
            db.add(new_size)

            # Create inventory history for initial stock
            if size_update.stock and size_update.stock > 0:
                history = InventoryHistory(
                    item_id=item_id,
                    change=size_update.stock,
                    type=InventoryChangeType.restock,
                    description="Initial stock for new size",
                    performed_by_id=user.id
                )
                db.add(history)

    # Handle size deletions
    if item_update.sizes_to_delete:
        for size_id in item_update.sizes_to_delete:
            if size_id not in existing_sizes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot delete size {size_id}: not found"
                )
            # Record the deletion in inventory history if there was stock
            size_to_delete = existing_sizes[size_id]
            if size_to_delete.stock > 0:
                history = InventoryHistory(
                    item_id=item_id,
                    change=-size_to_delete.stock,  # Negative change to remove all stock
                    type=InventoryChangeType.correction,
                    description=f"Stock removed due to size deletion: {size_to_delete.size_label}",
                    performed_by_id=user.id
                )
                db.add(history)
            db.delete(size_to_delete)

    db.commit()
    db.refresh(db_item)
    return db_item

@router.post("/inventory/restock/")
async def restock_item(
    restock: RestockRequest,
    db: Session = Depends(get_db),
    token: dict = Depends(validate_admin)
):
    # Verify item exists
    item = db.query(Item).filter(Item.id == restock.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Look up the performing user by username in the token
    username = token.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Performing user not found")

    # Find the specific size
    size = db.query(ItemSize).filter(
        ItemSize.item_id == restock.item_id,
        ItemSize.size_label == restock.size_label
    ).first()
    if not size:
        raise HTTPException(status_code=404, detail="Size not found for this item")

    # Update the stock in ItemSize
    size.stock += restock.quantity

    # Create inventory history entry with the correct user.id
    history = InventoryHistory(
        item_id=restock.item_id,
        change=restock.quantity,
        type=InventoryChangeType.restock,
        description=restock.description,
        performed_by_id=user.id
    )
    db.add(history)
    db.commit()
    return {"message": "Restock recorded successfully", "new_stock": size.stock}


@router.get("/inventory/history/")
async def get_inventory_history(
    item_id: Optional[str] = None,
    type: Optional[InventoryChangeType] = None,
    date_range: Optional[DateRangeFilter] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    query = db.query(InventoryHistory)
    
    if item_id:
        query = query.filter(InventoryHistory.item_id == item_id)
    if type:
        query = query.filter(InventoryHistory.type == type)
    if date_range:
        if date_range.start_date:
            query = query.filter(InventoryHistory.date >= date_range.start_date)
        if date_range.end_date:
            query = query.filter(InventoryHistory.date <= date_range.end_date)
    
    return query.order_by(InventoryHistory.date.desc()).all()

# --- Sales Management ---
@router.get("/sales/")
async def get_sales(
    date_range: Optional[DateRangeFilter] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    query = db.query(Order)
    
    if date_range:
        if date_range.start_date:
            query = query.filter(Order.date >= date_range.start_date)
        if date_range.end_date:
            query = query.filter(Order.date <= date_range.end_date)
    
    return query.order_by(Order.date.desc()).all()

# --- User Management ---
@router.get("/users/")
async def get_users(
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    return db.query(User).all() 