from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, cast, Integer
from typing import Optional
from pydantic import BaseModel
from app.core.security import validate_admin_or_cashier

from app.db.db import get_db
from app.db.models import Item, ItemSize, Category, Due, Order, OrderItem, InventoryHistory, InventoryChangeType, User, Shopper
from app.api.schemas.enhanced_order import EnhancedOrderCreate, EnhancedOrderResponse, CashierInfo, ShopperInfo
from app.api.schemas.order import OrderItemResponse
from app.api.routes.cashier import validate_cashier

router = APIRouter()

@router.post("/orders/enhanced", response_model=EnhancedOrderResponse, status_code=201)
def create_enhanced_order_for_cashier(
    order: EnhancedOrderCreate,
    db: Session = Depends(get_db),
    token: dict = Depends(validate_cashier)
):
    """
    Create a new order with enhanced payment handling.
    This endpoint handles complex payment scenarios including:
    - Partial payments
    - Payments toward previous dues
    - Advance payments
    """
    username = token.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Cashier not found")

    shopper_id = None
    shopper = None
    if order.customer_code:
        shopper = db.query(Shopper).filter(Shopper.customer_code == order.customer_code).first()
        if not shopper:
            raise HTTPException(status_code=404, detail=f"Shopper with code {order.customer_code} not found")
        shopper_id = shopper.id

    # Calculate order total
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

        # Update inventory
        item_size.stock -= item_data.quantity
        db.add(InventoryHistory(
            item_id=item_data.item_id,
            change=-item_data.quantity,
            type=InventoryChangeType.sale,
            description=f"Sale via cashier. Order Item ID: {order_item.id}",
            performed_by_id=user.id
        ))

    # Generate transaction ID
    last_numeric_id = db.query(func.max(cast(Order.transaction_id, Integer)))\
        .filter(Order.transaction_id.op('REGEXP')('^[0-9]+$')).scalar() or 0
    next_transaction_id = str(max(last_numeric_id, 999) + 1)

    # Create the order
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

    # Handle payment logic if customer code is provided
    remaining_dues = 0.0
    remaining_order_balance = 0.0
    
    if shopper_id and order.payment_amount is not None and order.payment_breakdown is not None:
        # Use frontend-calculated payment breakdown
        order_payment = order.payment_breakdown.order_payment
        dues_payment = order.payment_breakdown.dues_payment
        advance_payment = getattr(order.payment_breakdown, 'advance_payment', 0.0)  # Default to 0 if not provided
        remaining_dues = order.payment_breakdown.remaining_dues
        remaining_order_balance = order.payment_breakdown.remaining_order_balance
        
        # Validate that the breakdown matches the payment amount
        # Include advance payment in validation
        total_allocated = order_payment + dues_payment + advance_payment
        if abs(total_allocated - order.payment_amount) > 0.01:
            raise HTTPException(status_code=400, detail="Payment breakdown does not match payment amount")
        
        # Validate that remaining values are consistent
        previous_dues = db.query(Due).filter(Due.shopper_id == shopper_id).all()
        total_previous_dues = sum(due.amount for due in previous_dues)
        
        # Use advance payment from payment breakdown if available, otherwise calculate it
        if not hasattr(order.payment_breakdown, 'advance_payment') or order.payment_breakdown.advance_payment is None:
            # Calculate advance payment (when payment exceeds order total + previous dues)
            # Advance payment = Total payment - (Order payment + Dues payment)
            advance_payment = max(0, order.payment_amount - (order_payment + dues_payment))
        
        if abs(remaining_dues - max(0, total_previous_dues - dues_payment)) > 0.01:
            raise HTTPException(status_code=400, detail="Remaining dues calculation is inconsistent")
        
        if abs(remaining_order_balance - max(0, total - order_payment)) > 0.01:
            raise HTTPException(status_code=400, detail="Remaining order balance calculation is inconsistent")
        
        # Create due records for payment toward previous dues
        if dues_payment > 0:
            payment_due = Due(
                shopper_id=shopper_id,
                order_id=new_order.id,
                amount=-dues_payment,  # Negative for payment
                description=f"Payment toward previous dues for Order {next_transaction_id}"
            )
            db.add(payment_due)
        
        # Create due record for remaining order balance if not fully paid
        if remaining_order_balance > 0:
            remaining_due = Due(
                shopper_id=shopper_id,
                order_id=new_order.id,
                amount=remaining_order_balance,
                description=f"Remaining balance for Order {next_transaction_id}"
            )
            db.add(remaining_due)
        
        # Handle advance payment (when payment exceeds order total + previous dues)
        if advance_payment > 0:
            advance_due = Due(
                shopper_id=shopper_id,
                order_id=new_order.id,
                amount=-advance_payment,  # Negative for advance payment
                description=f"Advance payment for future purchases. Order {next_transaction_id}"
            )
            db.add(advance_due)
        
        # If fully paid, no need to create a due for the order
    elif shopper_id and not order.is_paid:
        # Fallback to original logic if no payment amount provided
        due = Due(
            shopper_id=shopper_id,
            order_id=new_order.id,
            amount=total,
            description=f"Order {next_transaction_id}"
        )
        db.add(due)

    db.commit()
    db.refresh(new_order)

    # Determine is_paid status based on whether there's a due record for this order
    # Order is considered paid if all due records are negative (payments/credits) or there are no dues
    order_dues = db.query(Due).filter(Due.order_id == new_order.id).all()
    order_is_paid = all(due.amount <= 0 for due in order_dues) if order_dues else True
    
    # Prepare order items response
    order_items_response = []
    for item in new_order.items:
        item_details = db.query(Item).filter(Item.id == item.item_id).first()
        order_items_response.append(
            OrderItemResponse(
                id=item.id,
                item_id=item.item_id,
                item_name=item_details.name if item_details else "Unknown",
                size_label=item.size_label,
                quantity=item.quantity,
                price_at_purchase=item.price_at_purchase,
                discount_applied=item.discount_applied
            )
        )
    
    # Get cashier details
    cashier = db.query(User).filter(User.id == new_order.cashier_id).first()
    cashier_info = CashierInfo(id=cashier.id, username=cashier.username) if cashier else None
    
    # Get shopper details if shopper exists
    shopper_info = None
    if shopper_id:
        shopper = db.query(Shopper).filter(Shopper.id == shopper_id).first()
        if shopper:
            shopper_info = ShopperInfo(
                id=shopper.id,
                customer_code=shopper.customer_code,
                name=shopper.name,
                phone_number=shopper.phone_number,
                address=shopper.address
            )
    
    # Prepare response
    return EnhancedOrderResponse(
        id=new_order.id,
        transaction_id=new_order.transaction_id,
        date=new_order.date,
        amount=new_order.amount,
        details=new_order.details,
        cashier_id=new_order.cashier_id,
        shopper_id=new_order.shopper_id,
        items=order_items_response,
        is_paid=order_is_paid,
        payment_amount=order.payment_amount,
        payment_breakdown=order.payment_breakdown,
        remaining_dues=remaining_dues if shopper_id else None,
        remaining_order_balance=remaining_order_balance if shopper_id else None,
        cashier=cashier_info,
        shopper=shopper_info
    )


@router.get("/orders/enhanced/sales", response_model=list[EnhancedOrderResponse])
def get_enhanced_sales_list(
    db: Session = Depends(get_db),
    token: dict = Depends(validate_admin_or_cashier)
):
    """
    Retrieve all sales (orders) with enhanced details including shopper and cashier information
    Accessible to both admin and cashier roles
    """
    orders = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.item),
        joinedload(Order.cashier),
        joinedload(Order.shopper)
    ).all()
    
    response_items = []
    for order in orders:
        # Get cashier info
        cashier_info = CashierInfo(
            id=order.cashier.id,
            username=order.cashier.username
        ) if order.cashier else None
        
        # Get shopper info
        shopper_info = ShopperInfo(
            id=order.shopper.id,
            customer_code=order.shopper.customer_code,
            name=order.shopper.name,
            phone_number=order.shopper.phone_number,
            address=order.shopper.address
        ) if order.shopper else None
        
        # Build order items with item names
        order_items = []
        for item in order.items:
            order_item = OrderItemResponse(
                id=item.id,
                order_id=item.order_id,
                item_id=item.item_id,
                item_name=item.item.name if item.item else "Unknown Item",
                size_label=item.size_label,
                quantity=item.quantity,
                price_at_purchase=item.price_at_purchase,
                discount_applied=item.discount_applied
            )
            order_items.append(order_item)
        
        # Determine is_paid status based on whether there's a due record for this order
        is_paid = True
        if order.shopper_id:
            due_record = db.query(Due).filter(Due.order_id == order.id, Due.amount > 0).first()
            is_paid = due_record is None
        
        # Create enhanced order response
        enhanced_order = EnhancedOrderResponse(
            id=order.id,
            transaction_id=order.transaction_id,
            date=order.date,
            amount=order.amount,
            details=order.details,
            cashier_id=order.cashier_id,
            shopper_id=order.shopper_id,
            items=order_items,
            is_paid=is_paid,
            payment_amount=None,
            payment_breakdown=None,
            remaining_dues=None,
            remaining_order_balance=None,
            cashier=cashier_info,
            shopper=shopper_info
        )
        response_items.append(enhanced_order)
    
    return response_items

@router.get("/orders/{order_id}", response_model=EnhancedOrderResponse)
def get_enhanced_order_by_id(
    order_id: str,
    db: Session = Depends(get_db),
    token: dict = Depends(validate_cashier)
):
    """
    Get an order by ID with enhanced details including shopper and cashier information
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Get order items with item details
    order_items_response = []
    for item in order.items:
        item_details = db.query(Item).filter(Item.id == item.item_id).first()
        order_items_response.append(
            OrderItemResponse(
                id=item.id,
                item_id=item.item_id,
                item_name=item_details.name if item_details else "Unknown",
                size_label=item.size_label,
                quantity=item.quantity,
                price_at_purchase=item.price_at_purchase,
                discount_applied=item.discount_applied
            )
        )
    
    # Get cashier details
    cashier = db.query(User).filter(User.id == order.cashier_id).first()
    cashier_info = CashierInfo(id=cashier.id, username=cashier.username) if cashier else None
    
    # Get shopper details if shopper exists
    shopper_info = None
    if order.shopper_id:
        shopper = db.query(Shopper).filter(Shopper.id == order.shopper_id).first()
        if shopper:
            shopper_info = ShopperInfo(
                id=shopper.id,
                customer_code=shopper.customer_code,
                name=shopper.name,
                phone_number=shopper.phone_number,
                address=shopper.address
            )
    
    # Determine is_paid status based on whether there's a due record for this order
    is_paid = True
    if order.shopper_id:
        due_record = db.query(Due).filter(Due.order_id == order.id, Due.amount > 0).first()
        is_paid = due_record is None
    
    # For now, we'll set these to None since we don't have the payment breakdown info for existing orders
    # In a real implementation, you might want to store this information with the order
    return EnhancedOrderResponse(
        id=order.id,
        transaction_id=order.transaction_id,
        date=order.date,
        amount=order.amount,
        details=order.details,
        cashier_id=order.cashier_id,
        shopper_id=order.shopper_id,
        items=order_items_response,
        is_paid=is_paid,
        payment_amount=None,
        payment_breakdown=None,
        remaining_dues=None,
        remaining_order_balance=None,
        cashier=cashier_info,
        shopper=shopper_info
    )
