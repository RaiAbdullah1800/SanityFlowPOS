from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
import os
from fastapi.encoders import jsonable_encoder
import json

from app.db.db import get_db
from app.db.models import (
    Item, ItemSize, InventoryHistory, InventoryChangeType,
    Order, OrderItem, User, UserRole, Category
)
from app.core.security import validate_admin
from app.db.supabase_client import supabase
from app.api.schemas.item import (
    ItemCreate, ItemResponse, ItemUpdate, ItemSizeCreate, ItemSizeUpdate,
    RestockRequest, DateRangeFilter, ItemSizeResponse, ItemListResponse
)
from app.api.schemas.category import CategoryResponse

# Constants for file validation
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/jpg", "image/webp"]
STORAGE_BUCKET = "item-images"  # Supabase storage bucket name

router = APIRouter(prefix="/admin", tags=["Admin"])

# Import models and schemas

# --- Helper Functions ---
async def validate_image(file: UploadFile) -> None:
    """Validate image file size and type"""
    # Check file size
    contents = await file.read()
    await file.seek(0)  # Reset file pointer
    
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum limit of {MAX_IMAGE_SIZE/1024/1024}MB"
        )
    
    # Check file type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type {file.content_type} not allowed. Allowed types: {', '.join(ALLOWED_IMAGE_TYPES)}"
        )

async def upload_image_to_supabase(file: UploadFile) -> str:
    """Upload image to Supabase storage and return the public URL"""
    try:
        # Generate unique filename with safe extension handling
        original_filename = file.filename or "upload.jpg"  # Default if filename is None
        file_extension = os.path.splitext(original_filename)[1].lower()
        if not file_extension:
            file_extension = ".jpg"  # Default extension if none provided
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        
        # Upload file to Supabase storage
        contents = await file.read()
        result = supabase.storage.from_(STORAGE_BUCKET).upload(
            unique_filename,
            contents
        )
        
        # Get public URL
        public_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(unique_filename)
        return public_url
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload image: {str(e)}"
        )
    finally:
        await file.close()

# --- Item Management ---
@router.post("/add-items/", status_code=status.HTTP_201_CREATED, response_model=ItemResponse)
async def add_item(
    image: UploadFile = File(...),
    item_data: str = Form(...),
    db: Session = Depends(get_db),
    token: dict = Depends(validate_admin)
):
    """
    Add a new item with image upload.
    
    - The image file will be validated and uploaded to Supabase storage
    - Item data should be provided as a JSON string in Form data
    - Returns the created item with all its details
    """
    try:
        # Parse item data from JSON string
        try:
            item_data_dict = json.loads(item_data)
            item = ItemCreate(**item_data_dict)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON format in item_data"
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )

        # Check if category exists if provided
        if item.category_id:
            category = db.query(Category).filter(Category.id == item.category_id).first()
            if not category:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Category with ID {item.category_id} not found"
                )

        # Get the performing user
        username = token.get("sub")
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(status_code=404, detail="Performing user not found")

        # Validate and upload image
        await validate_image(image)
        image_url = await upload_image_to_supabase(image)

        # Create the item with the image URL and category
        db_item = Item(
            name=item.name,
            image_url=image_url,
            category_id=item.category_id
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

    except HTTPException:
        raise
    except Exception as e:
        # If anything fails, ensure the transaction is rolled back
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create item: {str(e)}"
        )

# We are moving the new endpoint to this location
# to avoid conflict with the /items/{item_id} route
@router.get("/items/details", response_model=List[ItemListResponse])
def get_items_with_details(
    search: Optional[str] = Query(None, description="Search by item name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get a list of items with their details including:
    - Item ID
    - Item name
    - Category information
    - List of sizes with size ID, size label, and current stock
    
    Supports search by item name and pagination.
    """
    # Build the query
    query = db.query(Item).options(joinedload(Item.sizes), joinedload(Item.category_obj))
    
    if search:
        # Case-insensitive search for items that contain the search string
        query = query.filter(Item.name.ilike(f"%{search}%"))
    
    # Apply pagination
    items = query.offset(skip).limit(limit).all()
    
    # Convert to the response model
    result = []
    for item in items:
        # Prepare the category data if exists
        category_data = None
        if item.category_obj:
            category_data = {
                "id": item.category_obj.id,
                "name": item.category_obj.name
            }
        
        # Prepare the sizes data
        sizes_data = []
        for size in item.sizes:
            sizes_data.append({
                "id": size.id,
                "size_label": size.size_label,
                "stock": size.stock
            })
        
        result.append({
            "id": item.id,
            "name": item.name,
            "category": category_data,
            "sizes": sizes_data
        })
    
    return result

@router.get("/items/{item_id}", response_model=ItemResponse)
def get_item(
    item_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get detailed information about a specific item including all its sizes and category
    """
    db_item = db.query(Item).options(joinedload(Item.category_obj))\
        .filter(Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")
    return db_item

@router.get("/items/", response_model=List[ItemResponse])
def list_items(
    category_id: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get a list of all items with their sizes and categories
    
    - category_id: Filter items by category
    - search: Search term to filter items by name
    """
    query = db.query(Item).options(joinedload(Item.category_obj))
    
    if category_id:
        query = query.filter(Item.category_id == category_id)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(Item.name.ilike(search_term))
    
    items = query.all()
    return items

@router.get("/items/list", response_model=List[ItemListResponse])
def list_items_with_details(
    search: Optional[str] = Query(None, description="Search by item name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get a list of items with their details including sizes and category.
    Supports search by item name and pagination.
    """
    # Build the query
    query = db.query(Item).options(joinedload(Item.sizes), joinedload(Item.category_obj))
    
    if search:
        # Case-insensitive search for items that contain the search string
        query = query.filter(Item.name.ilike(f"%{search}%"))
    
    # Apply pagination
    items = query.offset(skip).limit(limit).all()
    
    # Convert to the response model
    result = []
    for item in items:
        # Prepare the category data if exists
        category_data = None
        if item.category_obj:
            category_data = {
                "id": item.category_obj.id,
                "name": item.category_obj.name
            }
        
        # Prepare the sizes data
        sizes_data = []
        for size in item.sizes:
            sizes_data.append({
                "id": size.id,
                "size_label": size.size_label,
                "stock": size.stock
            })
        
        result.append({
            "id": item.id,
            "name": item.name,
            "category": category_data,
            "sizes": sizes_data
        })
    
    return result

@router.put("/items/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: str,
    image: Optional[UploadFile] = File(None),
    item_data: str = Form(...),
    db: Session = Depends(get_db),
    token: dict = Depends(validate_admin)
):
    """Update an item's details, including its image, sizes, etc."""
    try:
        # Parse item data from JSON string
        try:
            item_data_dict = json.loads(item_data)
            item_update = ItemUpdate(**item_data_dict)
            
            # Check if category exists if provided
            if item_update.category_id:
                category = db.query(Category).filter(Category.id == item_update.category_id).first()
                if not category:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Category with ID {item_update.category_id} not found"
                    )
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON format in item_data"
            )
        
        # Get the performing user
        username = token.get("sub")
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(status_code=404, detail="Performing user not found")

        # First verify the item exists
        db_item = db.query(Item).filter(Item.id == item_id).first()
        if not db_item:
            raise HTTPException(status_code=404, detail="Item not found")

        # Handle image update if provided
        if image:
            await validate_image(image)
            image_url = await upload_image_to_supabase(image)
            db_item.image_url = image_url

        # Update item fields
        update_data = item_update.dict(exclude_unset=True, exclude={"sizes", "sizes_to_delete"})
        for field, value in update_data.items():
            setattr(db_item, field, value)

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

        try:
            db.commit()
            db.refresh(db_item)
            return db_item
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update item: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process update: {str(e)}"
        )

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
    start_date: Optional[datetime] = Query(None, description="Start date for filtering"),
    end_date: Optional[datetime] = Query(None, description="End date for filtering"),
    search: Optional[str] = Query(None, description="Search term for item name or username"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, le=100),
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    # Query with joins to get related data
    query = db.query(
        InventoryHistory,
        Item.name.label('item_name'),
        User.username.label('username')
    ).join(Item, InventoryHistory.item_id == Item.id
    ).join(User, InventoryHistory.performed_by_id == User.id)
    
    if item_id:
        query = query.filter(InventoryHistory.item_id == item_id)
    if type:
        query = query.filter(InventoryHistory.type == type)
    if start_date:
        query = query.filter(InventoryHistory.date >= start_date)
    if end_date:
        query = query.filter(InventoryHistory.date <= end_date)
    if search:
        search_term = f"%{search}%"
        query = query.filter(or_(
            Item.name.ilike(search_term),
            User.username.ilike(search_term)
        ))
    
    # Apply pagination
    total = query.count()
    results = query.order_by(InventoryHistory.date.desc()).offset(skip).limit(limit).all()

    
    # Format response
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "data": [{
            "id": r.InventoryHistory.id,
            "type": r.InventoryHistory.type,
            "change": r.InventoryHistory.change,
            "date": r.InventoryHistory.date,
            "item_name": r.item_name,
            "username": r.username,
            "description": r.InventoryHistory.description
        } for r in results]
    }

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

@router.delete("/items/{item_id}/image", status_code=status.HTTP_200_OK)
async def delete_item_image(
    item_id: str,
    db: Session = Depends(get_db),
    token: dict = Depends(validate_admin)
):
    """Delete an item's image from both Supabase storage and database"""
    try:
        # Get the item from the database
        db_item = db.query(Item).filter(Item.id == item_id).first()
        if not db_item:
            raise HTTPException(status_code=404, detail="Item not found")

        if not db_item.image_url:
            raise HTTPException(
                status_code=400,
                detail="Item does not have an image to delete"
            )

        try:
            # Extract path after bucket name (supports nested paths)
            if f"{STORAGE_BUCKET}/" not in db_item.image_url:
                raise ValueError("Invalid image URL format")

            file_path = db_item.image_url.split(f"{STORAGE_BUCKET}/")[-1].split("?")[0]


            # Try to delete from Supabase storage
            delete_response = supabase.storage.from_(STORAGE_BUCKET).remove([file_path])


        except Exception as e:
            print(f"Warning: Failed to delete image from storage: {str(e)}")

        # Remove image from DB
        db_item.image_url = None
        db.commit()

        return {"message": "Image deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete image: {str(e)}"
        )





# --- Delete Endpoints ---

@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    item_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Delete an item and all its associated data.

    This will permanently remove:
    - The item itself
    - All associated item sizes
    - All inventory history for the item
    - The item's image from the storage bucket

    This action is irreversible.
    """
    db_item = db.query(Item).filter(Item.id == item_id).first()

    if not db_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )

    try:
        # Delete the image from Supabase storage if it exists
        if db_item.image_url:
            try:
                # Extract the file name from the URL
                file_name = db_item.image_url.split(f"{STORAGE_BUCKET}/")[-1]
                if file_name:
                    supabase.storage.from_(STORAGE_BUCKET).remove([file_name])
            except Exception as e:
                # Log the error but proceed with DB deletion
                print(f"Warning: Failed to delete image '{db_item.image_url}' from storage: {e}")


        # Delete related records
        db.query(InventoryHistory).filter(InventoryHistory.item_id == item_id).delete(synchronize_session=False)
        db.query(OrderItem).filter(OrderItem.item_id == item_id).delete(synchronize_session=False)
        db.query(ItemSize).filter(ItemSize.item_id == item_id).delete(synchronize_session=False)

        # Delete the item itself
        db.delete(db_item)
        db.commit()

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete item and its related data: {str(e)}"
        )

    return None


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: str,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Delete a category.

    A category can only be deleted if it has no items associated with it.
    If there are items linked to the category, the deletion will be blocked
    to prevent orphaned items.
    """
    db_category = db.query(Category).filter(Category.id == category_id).first()

    if not db_category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found"
        )

    # Check if any items are associated with this category
    associated_items_count = db.query(Item).filter(Item.category_id == category_id).count()
    if associated_items_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete category. It is associated with {associated_items_count} item(s)."
        )

    try:
        db.delete(db_category)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete category: {str(e)}"
        )

    return None
