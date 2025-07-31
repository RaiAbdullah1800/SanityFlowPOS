from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from app.db.db import get_db
from app.db.models import Item, ItemSize, Category
from app.api.schemas.item import ItemListResponse
from app.api.schemas.category import CategoryResponse
from app.api.schemas.order import OrderCreate, OrderResponse, OrderItemResponse, PaginatedSalesResponse
from app.db.models import Order, OrderItem, InventoryHistory, InventoryChangeType, User
from app.core.security import validate_cashier

router = APIRouter(prefix="/cashier", tags=["Cashier"])

@router.get("/items/", response_model=List[ItemListResponse])
def list_items_for_cashier(
    search: Optional[str] = Query(None, description="Search by item name"),
    category_id: Optional[str] = Query(None, description="Filter by category id"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    _: dict = Depends(validate_cashier)
):
    """
    List items for cashier with search, pagination, and category filter.
    Each item includes: id, name, image_url, category, sizes (with stock, price, discount, etc).
    """
    query = db.query(Item).options(joinedload(Item.sizes), joinedload(Item.category_obj))
    if search:
        query = query.filter(Item.name.ilike(f"%{search}%"))
    if category_id:
        query = query.filter(Item.category_id == category_id)
    items = query.offset(skip).limit(limit).all()

    result = []
    for item in items:
        category_data = None
        if item.category_obj:
            category_data = {
                "id": item.category_obj.id,
                "name": item.category_obj.name
            }
        sizes_data = []
        for size in item.sizes:
            sizes_data.append({
                "id": size.id,
                "size_label": size.size_label,
                "price": size.price,
                "discount": size.discount,
                "stock": size.stock,
                "created_at": size.created_at
            })
        result.append({
            "id": item.id,
            "name": item.name,
            "image_url": item.image_url,
            "category": category_data,
            "sizes": sizes_data
        })
    return result

@router.get("/categories", response_model=List[CategoryResponse])
def list_categories_for_cashier(
    db: Session = Depends(get_db),
    _: dict = Depends(validate_cashier)
):
    """
    List all available categories for cashier item filtering.
    """
    categories = db.query(Category).order_by(Category.name).all()
    return categories

@router.post("/orders", response_model=OrderResponse)
def create_order_for_cashier(
    order: OrderCreate,
    db: Session = Depends(get_db),
    token: dict = Depends(validate_cashier)
):
    """
    Create a new order as cashier.
    """
    # Get cashier user
    username = token.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Cashier not found")

    # Calculate total amount and build order items
    total = 0.0
    order_items = []
    for item in order.items:
        size = db.query(ItemSize).filter(ItemSize.item_id == item.item_id, ItemSize.size_label == item.size_label).first()
        if not size:
            db.rollback()
            raise HTTPException(status_code=404, detail=f"Size {item.size_label} for item {item.item_id} not found")
        if size.stock < item.quantity:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"Not enough stock for item {item.item_id} size {item.size_label}")
        # Use backend price and discount
        price = size.price
        discount = size.discount or 0.0
        subtotal = (price - discount) * item.quantity
        total += subtotal
        order_items.append(OrderItem(
            item_id=item.item_id,
            size_label=item.size_label,
            quantity=item.quantity,
            price_at_purchase=price,
            discount_applied=discount
        ))
        # Update inventory and add inventory history
        size.stock -= item.quantity
        db.add(InventoryHistory(
            item_id=item.item_id,
            change=-item.quantity,
            type=InventoryChangeType.sale,
            description=f"Sold {item.quantity} of size {item.size_label}",
            performed_by_id=user.id
        ))

    total -= order.global_discount or 0.0
    if total < 0:
        total = 0.0

    # Create Order
    import uuid
    new_order = Order(
        transaction_id=str(uuid.uuid4()),
        amount=total,
        global_discount=order.global_discount or 0.0,
        details=order.details,
        cashier_id=user.id,
        items=order_items
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    # Eagerly load item relationship for all order items
    for oi in new_order.items:
        _ = oi.item  # Access to trigger loading if not already loaded

    # Prepare response
    return OrderResponse(
        id=new_order.id,
        transaction_id=new_order.transaction_id,
        date=new_order.date,
        amount=new_order.amount,
        global_discount=new_order.global_discount,
        details=new_order.details,
        cashier_id=new_order.cashier_id,
        items=[OrderItemResponse(
            id=oi.id,
            item_id=oi.item_id,
            item_name=oi.item.name if oi.item else "",
            size_label=oi.size_label,
            quantity=oi.quantity,
            price_at_purchase=oi.price_at_purchase,
            discount_applied=oi.discount_applied
        ) for oi in new_order.items]
    )

# Remove the existing sales endpoint
# This has been moved to shared.py for admin/cashier access
