from fastapi import APIRouter, Depends, Query, HTTPException, Path, Body
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from pydantic import BaseModel
from app.db.db import get_db
from app.db.models import Item, ItemSize, Category
from app.api.schemas.item import ItemListResponse
from app.api.schemas.category import CategoryResponse
from app.api.schemas.order import OrderCreate, OrderResponse, OrderItemResponse, PaginatedSalesResponse
from app.db.models import Order, OrderItem, InventoryHistory, InventoryChangeType, User
from app.core.security import validate_cashier

router = APIRouter(prefix="/cashier", tags=["Cashier"])

class ReturnItemRequest(BaseModel):
    item_id: str
    quantity: int = 1

class ReturnRequest(BaseModel):
    item_returns: Optional[List[ReturnItemRequest]] = None
    reason: str = "Customer return"
    return_full_order: bool = False

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
    Each item includes: id, name, image_url, category, sizes (with stock, price, discount percent, etc).
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
                "name": item.category_obj.name,
                "discount": item.category_obj.discount
            }
        sizes_data = []
        for size in item.sizes:
            # Determine effective discount: category overrides item-size discount ONLY if > 0
            category_discount = item.category_obj.discount if item.category_obj else None
            if category_discount is not None and category_discount > 0:
                effective_discount = category_discount
            else:
                effective_discount = (size.discount or 0.0)
            sizes_data.append({
                "id": size.id,
                "size_label": size.size_label,
                "price": size.price,
                "discount": size.discount,
                "effective_discount": effective_discount,
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
        size = db.query(ItemSize).filter(
            ItemSize.item_id == item.item_id, ItemSize.size_label == item.size_label
        ).first()
        if not size:
            db.rollback()
            raise HTTPException(status_code=404, detail=f"Size {item.size_label} for item {item.item_id} not found")
        if size.stock < item.quantity:
            db.rollback()
            raise HTTPException(status_code=400, detail=f"Not enough stock for item {item.item_id} size {item.size_label}")
        # Use backend price and percentage discount (category overrides item-size)
        price = size.price
        # Load item's category to check for category-level discount
        item_obj = db.query(Item).options(joinedload(Item.category_obj)).filter(Item.id == item.item_id).first()
        category_discount = item_obj.category_obj.discount if (item_obj and item_obj.category_obj) else None
        if category_discount is not None and category_discount > 0:
            discount_percent = category_discount
        else:
            discount_percent = (size.discount or 0.0)
        effective_price = price * (1 - (discount_percent / 100.0))
        subtotal = effective_price * item.quantity
        total += subtotal
        order_items.append(OrderItem(
            item_id=item.item_id,
            size_label=item.size_label,
            quantity=item.quantity,
            price_at_purchase=price,
            discount_applied=discount_percent
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

    # No global discount
    if total < 0:
        total = 0.0

    # Create Order
    import uuid
    new_order = Order(
        transaction_id=str(uuid.uuid4()),
        amount=total,
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
        ) for oi in new_order.items],
        has_been_returned=False
    )

# Remove the existing sales endpoint
# This has been moved to shared.py for admin/cashier access

@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order_by_id(
    order_id: str = Path(..., description="ID of the order to retrieve"),
    db: Session = Depends(get_db),
    token: dict = Depends(validate_cashier)
):
    """
    Retrieve order details by order ID for cashier.
    Returns the same structure as the order creation endpoint.
    """
    # Get cashier user
    username = token.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Cashier not found")

    # Find the order
    order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.item)
    ).filter(Order.id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Check if order belongs to this cashier (optional security check)
    # Uncomment the following lines if you want to restrict cashiers to only view their own orders
    # if order.cashier_id != user.id:
    #     raise HTTPException(status_code=403, detail="Not authorized to view this order")
    
    # Check if order has been returned
    # Look for any return records associated with this order
    has_been_returned = False
    return_records = db.query(Order).filter(
        Order.transaction_id.like(f"RETURN_{order.transaction_id}%")
    ).first()
    
    if return_records:
        has_been_returned = True
    else:
        # Also check if individual items have been returned
        for order_item in order.items:
            existing_returns = db.query(InventoryHistory).filter(
                InventoryHistory.description.like(f"%Return%Order Item ID: {order_item.id}%")
            ).first()
            if existing_returns:
                has_been_returned = True
                break
    
    # Aggregate items to show net quantities (original purchases minus returns)
    aggregated_items = {}
    for oi in order.items:
        key = (oi.item_id, oi.size_label)
        if key not in aggregated_items:
            aggregated_items[key] = {
                'id': oi.id,
                'item_id': oi.item_id,
                'item_name': oi.item.name if oi.item else "",
                'size_label': oi.size_label,
                'quantity': 0,
                'price_at_purchase': oi.price_at_purchase,
                'discount_applied': oi.discount_applied
            }
        aggregated_items[key]['quantity'] += oi.quantity
    
    # Filter out items with zero or negative quantities (fully returned)
    items_list = [item for item in aggregated_items.values() if item['quantity'] > 0]
    
    items=[OrderItemResponse(
        id=item['id'],
        item_id=item['item_id'],
        item_name=item['item_name'],
        size_label=item['size_label'],
        quantity=item['quantity'],
        price_at_purchase=item['price_at_purchase'],
        discount_applied=item['discount_applied']
    ) for item in items_list]
    
    # Prepare response with the same structure as order creation
    return OrderResponse(
        id=order.id,
        transaction_id=order.transaction_id,
        date=order.date,
        amount=order.amount,
        details=order.details,
        cashier_id=order.cashier_id,
        items=items,
        has_been_returned=has_been_returned
    )

@router.post("/orders/{order_id}/returns")
def process_return(
    order_id: str = Path(..., description="ID of the order"),
    return_request: ReturnRequest = Body(...),
    db: Session = Depends(get_db),
    token: dict = Depends(validate_cashier)
):
    """
    Process item returns for an order.
    If return_full_order is True, the entire order is returned.
    If item_returns is provided, only those specific items are returned with their quantities.
    """
    # Get cashier user
    username = token.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Cashier not found")

    # Find the order
    order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.item)
    ).filter(Order.id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Check if order has already been fully returned
    return_records = db.query(Order).filter(
        Order.transaction_id.like(f"RETURN_{order.transaction_id}%")
    ).first()
    
    # Also check if all items have been returned
    all_items_returned = True
    for order_item in order.items:
        existing_returns = db.query(InventoryHistory).filter(
            InventoryHistory.description.like(f"%Return%Order Item ID: {order_item.id}%")
        ).all()
        
        total_returned = sum([abs(hist.change) for hist in existing_returns])
        if total_returned < order_item.quantity:
            all_items_returned = False
            break
    
    if return_records and all_items_returned:
        raise HTTPException(status_code=400, detail="This order has already been fully returned and cannot be updated further.")
    
    # Extract parameters from request
    item_returns = return_request.item_returns
    reason = return_request.reason
    return_full_order = return_request.return_full_order
    
    # Process returns based on request parameters
    if return_full_order:
        # Return entire order (all items)
        # First check if the entire order has already been returned
        existing_order_returns = db.query(InventoryHistory).filter(
            InventoryHistory.description.like(f"%Return%Entire Order ID: {order.id}%")
        ).first()
        
        if existing_order_returns:
            raise HTTPException(status_code=400, detail="This order has already been returned")
        
        returned_items = []
        return_order_items = []
        
        for order_item in order.items:
            # Check if this specific item has already been returned
            existing_item_returns = db.query(InventoryHistory).filter(
                InventoryHistory.item_id == order_item.item_id,
                InventoryHistory.description.like(f"%Return%Order Item ID: {order_item.id}%")
            ).all()
            
            total_item_returned = sum([abs(hist.change) for hist in existing_item_returns])
            
            # Only return items that haven't been fully returned
            quantity_to_return = order_item.quantity - total_item_returned
            
            if quantity_to_return > 0:
                # Find the item size to update stock
                item_size = db.query(ItemSize).filter(
                    ItemSize.item_id == order_item.item_id,
                    ItemSize.size_label == order_item.size_label
                ).first()
                
                if not item_size:
                    db.rollback()
                    raise HTTPException(status_code=404, detail=f"Item size not found for {order_item.item.name}")
                
                # Update stock
                item_size.stock += quantity_to_return
                
                # Add inventory history
                db.add(InventoryHistory(
                    item_id=order_item.item_id,
                    change=quantity_to_return,
                    type=InventoryChangeType.correction,
                    description=f"Return: {reason}. Order Item ID: {order_item.id}. Returned entire order. Returned {quantity_to_return} of size {order_item.size_label}",
                    performed_by_id=user.id
                ))
                
                # Create negative sales record for return
                return_order_items.append(OrderItem(
                    item_id=order_item.item_id,
                    size_label=order_item.size_label,
                    quantity=-quantity_to_return,  # Negative quantity for return
                    price_at_purchase=order_item.price_at_purchase,
                    discount_applied=order_item.discount_applied
                ))
                
                returned_items.append({
                    "item_name": order_item.item.name if order_item.item else "",
                    "quantity": quantity_to_return,
                    "size_label": order_item.size_label,
                    "price_at_purchase": order_item.price_at_purchase,
                    "discount_applied": order_item.discount_applied
                })
        
        # Create a separate return order for tracking
        if returned_items and return_order_items:
            # Calculate total return amount
            total_return_amount = sum([
                (item.price_at_purchase * (1 - ((item.discount_applied or 0) / 100.0))) * abs(item.quantity)
                for item in return_order_items
            ])
            
            # Create return order with unique transaction ID
            import uuid
            unique_id = str(uuid.uuid4())[:8]
            return_order = Order(
                transaction_id=f"RETURN_{order.transaction_id}_{unique_id}",
                amount=-total_return_amount,  
                details=f"Return for order {order.transaction_id}: {reason}",
                cashier_id=user.id
            )
            db.add(return_order)
            db.flush()  # Get the return order ID
            
            # Associate return order items with the return order
            for return_item in return_order_items:
                return_item.order_id = return_order.id
                db.add(return_item)
            
            # Add a record for the entire order return
            # Use the first item's ID as a placeholder for the order return record
            first_item_id = order.items[0].item_id if order.items else None
            if first_item_id:
                db.add(InventoryHistory(
                    item_id=first_item_id,
                    change=0,  # No actual inventory change
                    type=InventoryChangeType.correction,
                    description=f"Return: {reason}. Entire Order ID: {order.id}. Returned {len(returned_items)} items.",
                    performed_by_id=user.id
                ))
        
        db.commit()
        
        if not returned_items:
            return {
                "message": "No items to return. All items in this order have already been returned.",
                "receipt": None,
                "returned_items": [],
                "total_items": 0
            }
        
        # Calculate total return amount for receipt
        total_return_amount = sum([
            (item['price_at_purchase'] * (1 - ((item['discount_applied'] or 0) / 100.0))) * item['quantity']
            for item in returned_items
        ])
        
        return {
            "message": f"Successfully returned entire order {order.transaction_id}",
            "receipt": {
                "return_transaction_id": return_order.transaction_id if 'return_order' in locals() else None,
                "original_order_id": order.id,
                "original_transaction_id": order.transaction_id,
                "return_date": return_order.date if 'return_order' in locals() else None,
                "reason": reason,
                "returned_items": returned_items,
                "total_items_returned": len(returned_items),
                "total_return_amount": total_return_amount
            },
            "returned_items": returned_items,
            "total_items": len(returned_items)
        }
    elif item_returns:
        # Return specific items with specified quantities
        returned_items = []
        return_order_items = []
        total_return_amount = 0.0
        
        # Validate all items first
        for return_item_request in item_returns:
            item_id = return_item_request.item_id
            quantity = return_item_request.quantity
            
            # Find the order item
            order_item = db.query(OrderItem).filter(
                OrderItem.id == item_id,
                OrderItem.order_id == order_id
            ).first()
            
            if not order_item:
                db.rollback()
                raise HTTPException(status_code=404, detail=f"Item {item_id} not found in order")
            
            # Check if this specific item has already been returned
            existing_returns = db.query(InventoryHistory).filter(
                InventoryHistory.item_id == order_item.item_id,
                InventoryHistory.description.like(f"%Return%Order Item ID: {order_item.id}%")
            ).all()
            
            total_returned = sum([abs(hist.change) for hist in existing_returns])
            
            # Check if return quantity is valid
            if quantity > (order_item.quantity - total_returned):
                db.rollback()
                raise HTTPException(status_code=400, detail=f"Return quantity exceeds remaining purchased quantity for {order_item.item.name if order_item.item else 'item'}. Already returned: {total_returned}, Requested: {quantity}, Available: {order_item.quantity - total_returned}")
        
        # Check if there are any items to return
        if not item_returns:
            return {
                "message": "No items specified for return.",
                "receipt": None,
                "returned_items": [],
                "total_items": 0
            }
            
        # Process all valid returns
        for return_item_request in item_returns:
            item_id = return_item_request.item_id
            quantity = return_item_request.quantity
            
            # Find the order item
            order_item = db.query(OrderItem).filter(
                OrderItem.id == item_id,
                OrderItem.order_id == order_id
            ).first()
            
            if not order_item:
                continue  # Should not happen as we validated above
            
            # Find the item size to update stock
            item_size = db.query(ItemSize).filter(
                ItemSize.item_id == order_item.item_id,
                ItemSize.size_label == order_item.size_label
            ).first()
            
            if not item_size:
                db.rollback()
                raise HTTPException(status_code=404, detail=f"Item size not found for {order_item.item.name}")
            
            # Update stock
            item_size.stock += quantity
            
            # Add inventory history
            db.add(InventoryHistory(
                item_id=order_item.item_id,
                change=quantity,
                type=InventoryChangeType.correction,
                description=f"Return: {reason}. Order Item ID: {order_item.id}. Returned {quantity} of size {order_item.size_label}",
                performed_by_id=user.id
            ))
            
            # Calculate return amount for this item
            item_return_amount = (order_item.price_at_purchase * (1 - ((order_item.discount_applied or 0)/100.0))) * quantity
            total_return_amount += item_return_amount
            
            # Create negative sales record for return
            return_order_items.append(OrderItem(
                item_id=order_item.item_id,
                size_label=order_item.size_label,
                quantity=-quantity,  # Negative quantity for return
                price_at_purchase=order_item.price_at_purchase,
                discount_applied=order_item.discount_applied
            ))
            
            returned_items.append({
                "item_name": order_item.item.name if order_item.item else "",
                "quantity": quantity,
                "size_label": order_item.size_label,
                "price_at_purchase": order_item.price_at_purchase,
                "discount_applied": order_item.discount_applied
            })
        
        # Create a single return order for all items
        if returned_items and return_order_items:
            # Create return order with unique transaction ID
            import uuid
            unique_id = str(uuid.uuid4())[:8]
            return_order = Order(
                transaction_id=f"RETURN_{order.transaction_id}_{unique_id}",
                amount=-total_return_amount,  
                details=f"Partial return for order {order.transaction_id}: {reason}",
                cashier_id=user.id
            )
            db.add(return_order)
            db.flush()  # Get the return order ID
            
            # Associate return order items with the return order
            for return_item in return_order_items:
                return_item.order_id = return_order.id
                db.add(return_item)
        
        db.commit()
        
        # Get the return order details for receipt
        return_order_details = None
        if 'return_order' in locals():
            return_order_details = {
                "return_transaction_id": return_order.transaction_id,
                "original_order_id": order.id,
                "original_transaction_id": order.transaction_id,
                "return_date": return_order.date,
                "reason": reason,
                "returned_items": returned_items,
                "total_items_returned": len(returned_items),
                "total_return_amount": total_return_amount
            }
        
        return {
            "message": f"Successfully returned {len(returned_items)} items",
            "receipt": return_order_details,
            "returned_items": returned_items,
            "total_items": len(returned_items)
        }
    else:
        raise HTTPException(status_code=400, detail="Either return_full_order must be true or item_returns must be provided")
