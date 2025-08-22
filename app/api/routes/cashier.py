from fastapi import APIRouter, Depends, Query, HTTPException, Path, Body
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, Integer, or_
from typing import List, Optional
from pydantic import BaseModel
from app.db.db import get_db
from app.db.models import Item, ItemSize, Category, Due
from app.api.schemas.item import ItemListResponse
from app.api.schemas.category import CategoryResponse
from app.api.schemas.order import OrderCreate, OrderResponse, OrderItemResponse, PaginatedSalesResponse
from app.db.models import Order, OrderItem, InventoryHistory, InventoryChangeType, User, Shopper, Due
from app.core.security import validate_cashier
router = APIRouter(prefix="/cashier", tags=["Cashier"])

class ReturnItemRequest(BaseModel):
    item_id: str
    quantity: int = 1

class ReturnRequest(BaseModel):
    item_returns: Optional[List[ReturnItemRequest]] = None
    reason: str = "Customer return"
    return_full_order: bool = False
    # How to allocate any refund amount that is not needed to clear dues
    # "cash" (default) or "advance" (store as credit)
    refund_method: Optional[str] = "cash"

def _compute_balances(db: Session, shopper_id: Optional[str]):
    """Compute aggregate dues and advance balances for a shopper.
    dues_balance: positive amount owed by shopper
    advance_balance: positive credit available to shopper
    """
    if not shopper_id:
        return {"dues_balance": 0.0, "advance_balance": 0.0}
    total = db.query(func.sum(Due.amount)).filter(Due.shopper_id == shopper_id).scalar() or 0.0
    if total > 0:
        return {"dues_balance": float(total), "advance_balance": 0.0}
    elif total < 0:
        return {"dues_balance": 0.0, "advance_balance": float(-total)}
    else:
        return {"dues_balance": 0.0, "advance_balance": 0.0}

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

@router.post("/orders", response_model=OrderResponse, status_code=201)
def create_order_for_cashier(
    order: OrderCreate,
    db: Session = Depends(get_db),
    token: dict = Depends(validate_cashier)
):
    """
    Create a new order as cashier.
    """
    username = token.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Cashier not found")

    shopper_id = None
    if order.customer_code:
        shopper = db.query(Shopper).filter(Shopper.customer_code == order.customer_code).first()
        if not shopper:
            raise HTTPException(status_code=404, detail=f"Shopper with code {order.customer_code} not found")
        shopper_id = shopper.id

    total = 0.0
    order_items = []
    for item_data in order.items:
        item_size = db.query(ItemSize).options(joinedload(ItemSize.item).joinedload(Item.category_obj)).filter(
            ItemSize.item_id == item_data.item_id,
            ItemSize.size_label == item_data.size_label
        ).first()
        if not item_size:
            raise HTTPException(status_code=404, detail=f"Item with ID {item_data.item_id} and size {item_data.size_label} not found")
        if item_size.stock < item_data.quantity:
            raise HTTPException(status_code=400, detail=f"Not enough stock for {item_size.item.name} ({item_data.size_label})")

        category_discount = item_size.item.category_obj.discount if item_size.item.category_obj else None
        effective_discount = category_discount if category_discount is not None and category_discount > 0 else (item_size.discount or 0.0)
        
        price_after_discount = item_size.price * (1 - (effective_discount / 100.0))
        total += price_after_discount * item_data.quantity

        order_item = OrderItem(
            item_id=item_data.item_id,
            size_label=item_data.size_label,
            quantity=item_data.quantity,
            price_at_purchase=item_size.price,
            discount_applied=effective_discount
        )
        order_items.append(order_item)

        item_size.stock -= item_data.quantity
        db.add(InventoryHistory(
            item_id=item_data.item_id,
            change=-item_data.quantity,
            type=InventoryChangeType.sale,
            description=f"Sale via cashier. Order Item ID: {order_item.id}",
            performed_by_id=user.id
        ))

    # Find the maximum numeric transaction ID and ensure it's at least 999
    last_numeric_id = db.query(func.max(cast(Order.transaction_id, Integer)))\
        .filter(Order.transaction_id.op('REGEXP')('^[0-9]+$')).scalar() or 0

    # Start from 1000 if the max ID is less than 999
    next_transaction_id = str(max(last_numeric_id, 999) + 1)

    new_order = Order(
        transaction_id=next_transaction_id,
        amount=total,
        details=order.details,
        cashier_id=user.id,
        shopper_id=shopper_id,
        items=order_items
    )
    db.add(new_order)
    db.flush()

    # Only create a due record if the customer is not paying (is_paid is False)
    if shopper_id and not order.is_paid:
        due = Due(
            shopper_id=shopper_id,
            order_id=new_order.id,
            amount=total,
            description=f"Order {next_transaction_id}"
        )
        db.add(due)

    db.commit()
    db.refresh(new_order)

    order_items_response = []
    for item in new_order.items:
        item_details = db.query(Item).options(joinedload(Item.category_obj)).filter(Item.id == item.item_id).first()
        category_name = ""
        if item_details and item_details.category_obj:
            category_name = item_details.category_obj.name
            
        order_items_response.append(
            OrderItemResponse(
                id=item.id,
                item_id=item.item_id,
                item_name=item_details.name if item_details else "Unknown",
                size_label=item.size_label,
                quantity=item.quantity,
                price_at_purchase=item.price_at_purchase,
                discount_applied=item.discount_applied,
                category_name=category_name
            )
        )

    shopper_info = None
    balance_summary = None
    if new_order.shopper_id:
        shopper = db.query(Shopper).filter(Shopper.id == new_order.shopper_id).first()
        if shopper:
            shopper_info = {
                "id": shopper.id,
                "customer_code": shopper.customer_code,
                "name": shopper.name,
                "phone_number": shopper.phone_number,
                "address": shopper.address
            }
        balance_summary = _compute_balances(db, new_order.shopper_id)

    return OrderResponse(
        id=new_order.id,
        transaction_id=new_order.transaction_id,
        date=new_order.date,
        amount=new_order.amount,
        details=new_order.details,
        cashier_id=new_order.cashier_id,
        shopper_id=new_order.shopper_id,
        items=order_items_response,
        has_been_returned=False,
        shopper=shopper_info,
        balance_summary=balance_summary
    )

# Remove the existing sales endpoint
# This has been moved to shared.py for admin/cashier access

@router.get("/orders/{identifier}", response_model=OrderResponse)
def get_order_by_identifier(
    identifier: str = Path(..., description="ID or Transaction ID of the order to retrieve"),
    db: Session = Depends(get_db),
    token: dict = Depends(validate_cashier)
):
    """
    Retrieve order details by order ID or transaction ID for cashier.
    """
    username = token.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Cashier not found")

    # Find the order by ID or transaction ID
    order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.item).joinedload(Item.category_obj)
    ).filter(or_(Order.id == identifier, Order.transaction_id == identifier)).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Check if the order has been returned
    has_been_returned = db.query(Order).filter(
        Order.transaction_id.like(f"RETURN_{order.transaction_id}%")
    ).first() is not None

    aggregated_items = {}
    for oi in order.items:
        key = (oi.item_id, oi.size_label)
        if key not in aggregated_items:
            category_name = ""
            if oi.item and oi.item.category_obj:
                category_name = oi.item.category_obj.name
            
            aggregated_items[key] = {
                'id': oi.id,
                'item_id': oi.item_id,
                'item_name': oi.item.name if oi.item else "",
                'size_label': oi.size_label,
                'quantity': 0,
                'price_at_purchase': oi.price_at_purchase,
                'discount_applied': oi.discount_applied,
                'category_name': category_name
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
        discount_applied=item['discount_applied'],
        category_name=item['category_name']
    ) for item in items_list]
    
    shopper_info = None
    balance_summary = None
    if order.shopper_id:
        shopper = db.query(Shopper).filter(Shopper.id == order.shopper_id).first()
        if shopper:
            shopper_info = {
                "id": shopper.id,
                "customer_code": shopper.customer_code,
                "name": shopper.name,
                "phone_number": shopper.phone_number,
                "address": shopper.address
            }
        balance_summary = _compute_balances(db, order.shopper_id)

    # Prepare response with the same structure as order creation
    return OrderResponse(
        id=order.id,
        transaction_id=order.transaction_id,
        date=order.date,
        amount=order.amount,
        details=order.details,
        cashier_id=order.cashier_id,
        items=items,
        has_been_returned=has_been_returned,
        shopper=shopper_info,
        balance_summary=balance_summary
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
            
            # Create return order with structured transaction ID: RETURN_<original_numeric>_<n>
            existing_returns_count = db.query(func.count(Order.id)).\
                filter(Order.transaction_id.like(f"RETURN_{order.transaction_id}%")).scalar() or 0
            return_txn_id = f"RETURN_{order.transaction_id}_{existing_returns_count + 1}"
            return_order = Order(
                transaction_id=return_txn_id,
                amount=-total_return_amount,  
                details=f"Return for order {order.transaction_id}: {reason}",
                cashier_id=user.id,
                shopper_id=order.shopper_id  # Link return order to the same customer as original order
            )
            db.add(return_order)
            db.flush()  # Get the return order ID
            
            # Associate return order items with the return order
            for return_item in return_order_items:
                return_item.order_id = return_order.id
                db.add(return_item)
            
            # Allocate refund to dues first, then cash or advance based on refund_method
            refund_method = (return_request.refund_method or "cash").lower()
            if refund_method not in ("cash", "advance"):
                refund_method = "cash"
            applied_to_dues = 0.0
            cash_refund = 0.0
            added_to_advance = 0.0
            balances_before = _compute_balances(db, order.shopper_id) if order.shopper_id else {"dues_balance": 0.0, "advance_balance": 0.0}

            if order.shopper_id:
                # Apply to existing dues first
                if balances_before["dues_balance"] > 0:
                    applied_to_dues = float(min(total_return_amount, balances_before["dues_balance"]))
                    if applied_to_dues > 0:
                        db.add(Due(
                            shopper_id=order.shopper_id,
                            amount=-applied_to_dues,
                            description=f"Return adjustment for order {order.transaction_id}. Return transaction: {return_txn_id}",
                            order_id=return_order.id
                        ))
                # Remaining can be cashed out or added to advance
                remaining = float(total_return_amount - applied_to_dues)
                if remaining > 0:
                    if refund_method == "advance":
                        db.add(Due(
                            shopper_id=order.shopper_id,
                            amount=-remaining,
                            description=f"Advance credit from return {return_txn_id}",
                            order_id=return_order.id
                        ))
                        added_to_advance = remaining
                    else:
                        cash_refund = remaining
            else:
                # Walk-in: refund as cash (force method to cash)
                refund_method = "cash"
                cash_refund = float(total_return_amount)
            
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
        
        # Shopper and balances after commit
        shopper_info = None
        balances_after = balances_before
        if order.shopper_id:
            shopper = db.query(Shopper).filter(Shopper.id == order.shopper_id).first()
            if shopper:
                shopper_info = {
                    "id": shopper.id,
                    "customer_code": shopper.customer_code,
                    "name": shopper.name,
                    "phone_number": shopper.phone_number,
                    "address": shopper.address
                }
            balances_after = _compute_balances(db, order.shopper_id)

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
                "total_return_amount": total_return_amount,
                "shopper": shopper_info,
                "refund_allocation": {
                    "refund_method": refund_method if 'refund_method' in locals() else "cash",
                    "applied_to_dues": applied_to_dues if 'applied_to_dues' in locals() else 0.0,
                    "cash_refund": cash_refund if 'cash_refund' in locals() else 0.0,
                    "added_to_advance": added_to_advance if 'added_to_advance' in locals() else 0.0
                },
                "balances": {
                    "before": balances_before,
                    "after": balances_after
                }
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
            # Create return order with structured transaction ID: RETURN_<original_numeric>_<n>
            existing_returns_count = db.query(func.count(Order.id)).\
                filter(Order.transaction_id.like(f"RETURN_{order.transaction_id}%")).scalar() or 0
            return_txn_id = f"RETURN_{order.transaction_id}_{existing_returns_count + 1}"
            return_order = Order(
                transaction_id=return_txn_id,
                amount=-total_return_amount,  
                details=f"Partial return for order {order.transaction_id}: {reason}",
                cashier_id=user.id,
                shopper_id=order.shopper_id  # Link return order to the same customer as original order
            )
            db.add(return_order)
            db.flush()  # Get the return order ID
            
            # Associate return order items with the return order
            for return_item in return_order_items:
                return_item.order_id = return_order.id
                db.add(return_item)
            
            # Allocate refund to dues first, then cash or advance based on refund_method
            refund_method = (return_request.refund_method or "cash").lower()
            if refund_method not in ("cash", "advance"):
                refund_method = "cash"
            applied_to_dues = 0.0
            cash_refund = 0.0
            added_to_advance = 0.0
            balances_before = _compute_balances(db, order.shopper_id) if order.shopper_id else {"dues_balance": 0.0, "advance_balance": 0.0}

            if order.shopper_id:
                # Apply to existing dues first
                if balances_before["dues_balance"] > 0:
                    applied_to_dues = float(min(total_return_amount, balances_before["dues_balance"]))
                    if applied_to_dues > 0:
                        db.add(Due(
                            shopper_id=order.shopper_id,
                            amount=-applied_to_dues,
                            description=f"Return adjustment for order {order.transaction_id}. Return transaction: {return_txn_id}",
                            order_id=return_order.id
                        ))
                # Remaining can be cashed out or added to advance
                remaining = float(total_return_amount - applied_to_dues)
                if remaining > 0:
                    if refund_method == "advance":
                        db.add(Due(
                            shopper_id=order.shopper_id,
                            amount=-remaining,
                            description=f"Advance credit from return {return_txn_id}",
                            order_id=return_order.id
                        ))
                        added_to_advance = remaining
                    else:
                        cash_refund = remaining
            else:
                # Walk-in: refund as cash (force method to cash)
                refund_method = "cash"
                cash_refund = float(total_return_amount)
        
        db.commit()
        
        # Get the return order details for receipt
        return_order_details = None
        if 'return_order' in locals():
            shopper_info = None
            balances_after = balances_before
            if order.shopper_id:
                shopper = db.query(Shopper).filter(Shopper.id == order.shopper_id).first()
                if shopper:
                    shopper_info = {
                        "id": shopper.id,
                        "customer_code": shopper.customer_code,
                        "name": shopper.name,
                        "phone_number": shopper.phone_number,
                        "address": shopper.address
                    }
                balances_after = _compute_balances(db, order.shopper_id)

            return_order_details = {
                "return_transaction_id": return_order.transaction_id,
                "original_order_id": order.id,
                "original_transaction_id": order.transaction_id,
                "return_date": return_order.date,
                "reason": reason,
                "returned_items": returned_items,
                "total_items_returned": len(returned_items),
                "total_return_amount": total_return_amount,
                "shopper": shopper_info,
                "refund_allocation": {
                    "refund_method": refund_method if 'refund_method' in locals() else "cash",
                    "applied_to_dues": applied_to_dues if 'applied_to_dues' in locals() else 0.0,
                    "cash_refund": cash_refund if 'cash_refund' in locals() else 0.0,
                    "added_to_advance": added_to_advance if 'added_to_advance' in locals() else 0.0
                },
                "balances": {
                    "before": balances_before,
                    "after": balances_after
                }
            }
        
        return {
            "message": f"Successfully returned {len(returned_items)} items",
            "receipt": return_order_details,
            "returned_items": returned_items,
            "total_items": len(returned_items)
        }
    else:
        raise HTTPException(status_code=400, detail="Either return_full_order must be true or item_returns must be provided")
