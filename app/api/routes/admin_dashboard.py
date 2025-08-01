from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from typing import List, Optional
from decimal import Decimal

from app.db.db import get_db
from app.db.models import Order, OrderItem, Item, ItemSize, Category, InventoryHistory, InventoryChangeType, User
from app.core.security import validate_admin
from app.api.schemas.admin_dashboard import (
    RevenueByDateResponse,
    TotalRevenueResponse,
    SalesByCategoryResponse,
    PaymentMethodBreakdownResponse,
    LowStockItemResponse,
    InventoryMovementResponse,
    BestSellingItemResponse,
    StaffPerformanceResponse
)

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])

@router.get("/revenue-by-date", response_model=List[RevenueByDateResponse])
async def get_revenue_by_date(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get revenue by date range
    """
    query = db.query(
        func.date(Order.date).label('date'),
        func.sum(Order.amount).label('total_revenue')
    ).group_by(func.date(Order.date)).order_by(func.date(Order.date))
    
    if start_date:
        query = query.filter(Order.date >= start_date)
    
    if end_date:
        query = query.filter(Order.date <= end_date)
    
    results = query.all()
    
    return [
        RevenueByDateResponse(
            date=result.date,
            total_revenue=float(result.total_revenue) if result.total_revenue else 0.0
        )
        for result in results
    ]

@router.get("/total-revenue", response_model=TotalRevenueResponse)
async def get_total_revenue(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get total revenue for a date range
    """
    query = db.query(func.sum(Order.amount).label('total_revenue'))
    
    if start_date:
        query = query.filter(Order.date >= start_date)
    
    if end_date:
        query = query.filter(Order.date <= end_date)
    
    result = query.first()
    
    return TotalRevenueResponse(
        total_revenue=float(result.total_revenue) if result.total_revenue else 0.0,
        start_date=datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None,
        end_date=datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    )

@router.get("/sales-by-category", response_model=List[SalesByCategoryResponse])
async def get_sales_by_category(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get sales by category
    """
    query = db.query(
        Category.name.label('category_name'),
        func.sum(OrderItem.quantity).label('total_quantity'),
        func.sum(OrderItem.quantity * OrderItem.price_at_purchase).label('total_revenue')
    ).join(Item, Item.id == OrderItem.item_id
    ).join(Category, Category.id == Item.category_id
    ).join(Order, Order.id == OrderItem.order_id)
    
    if start_date:
        query = query.filter(Order.date >= start_date)
    
    if end_date:
        query = query.filter(Order.date <= end_date)
    
    results = query.group_by(Category.name).all()
    
    return [
        SalesByCategoryResponse(
            category_name=result.category_name,
            total_quantity=result.total_quantity or 0,
            total_revenue=float(result.total_revenue) if result.total_revenue else 0.0
        )
        for result in results
    ]

@router.get("/payment-method-breakdown", response_model=List[PaymentMethodBreakdownResponse])
async def get_payment_method_breakdown(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get payment method breakdown (using details field to determine payment method)
    """
    # Since we don't have a separate payment method field, we'll use the details field
    # and assume it contains payment information
    query = db.query(
        Order.details,
        func.count(Order.id).label('transaction_count'),
        func.sum(Order.amount).label('total_amount')
    )
    
    if start_date:
        query = query.filter(Order.date >= start_date)
    
    if end_date:
        query = query.filter(Order.date <= end_date)
    
    results = query.group_by(Order.details).all()
    
    # Process results to extract payment methods
    payment_methods = {}
    for result in results:
        # For now, we'll use a simple approach - in a real system, you'd have a payment_method field
        payment_method = result.details if result.details else "Not specified"
        if payment_method not in payment_methods:
            payment_methods[payment_method] = {
                "transaction_count": 0,
                "total_amount": 0.0
            }
        payment_methods[payment_method]["transaction_count"] += result.transaction_count
        payment_methods[payment_method]["total_amount"] += float(result.total_amount or 0.0)
    
    return [
        PaymentMethodBreakdownResponse(
            payment_method=method,
            transaction_count=data["transaction_count"],
            total_amount=data["total_amount"]
        )
        for method, data in payment_methods.items()
    ]

@router.get("/low-stock-items", response_model=List[LowStockItemResponse])
async def get_low_stock_items(
    threshold: int = 10,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get low stock items
    """
    results = db.query(
        Item.name.label('item_name'),
        ItemSize.size_label.label('size_label'),
        ItemSize.stock.label('current_stock')
    ).join(ItemSize, Item.id == ItemSize.item_id
    ).filter(ItemSize.stock <= threshold
    ).order_by(ItemSize.stock).all()
    
    return [
        LowStockItemResponse(
            item_name=result.item_name,
            size_label=result.size_label,
            current_stock=result.current_stock
        )
        for result in results
    ]

@router.get("/inventory-movement", response_model=List[InventoryMovementResponse])
async def get_inventory_movement(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get inventory movement reports
    """
    query = db.query(
        Item.name.label('item_name'),
        InventoryHistory.type.label('change_type'),
        func.sum(InventoryHistory.change).label('total_change')
    ).join(Item, Item.id == InventoryHistory.item_id)
    
    if start_date:
        query = query.filter(InventoryHistory.date >= start_date)
    
    if end_date:
        query = query.filter(InventoryHistory.date <= end_date)
    
    results = query.group_by(Item.name, InventoryHistory.type).all()
    
    return [
        InventoryMovementResponse(
            item_name=result.item_name,
            change_type=result.change_type.value,
            total_change=int(result.total_change) if result.total_change else 0
        )
        for result in results
    ]

@router.get("/best-selling-items", response_model=List[BestSellingItemResponse])
async def get_best_selling_items(
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get best-selling items
    """
    query = db.query(
        Item.name.label('item_name'),
        func.sum(OrderItem.quantity).label('total_sold')
    ).join(Item, Item.id == OrderItem.item_id
    ).join(Order, Order.id == OrderItem.order_id)
    
    if start_date:
        query = query.filter(Order.date >= start_date)
    
    if end_date:
        query = query.filter(Order.date <= end_date)
    
    results = query.group_by(Item.name).order_by(func.sum(OrderItem.quantity).desc()).limit(limit).all()
    
    return [
        BestSellingItemResponse(
            item_name=result.item_name,
            total_sold=result.total_sold or 0
        )
        for result in results
    ]

@router.get("/staff-performance", response_model=List[StaffPerformanceResponse])
async def get_staff_performance(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    _: dict = Depends(validate_admin)
):
    """
    Get transaction count per staff member
    """
    query = db.query(
        User.username.label('staff_name'),
        func.count(Order.id).label('transaction_count'),
        func.sum(Order.amount).label('total_revenue')
    ).join(Order, Order.cashier_id == User.id
    ).filter(User.role == 'cashier')  # Only cashiers have transactions
    
    if start_date:
        query = query.filter(Order.date >= start_date)
    
    if end_date:
        query = query.filter(Order.date <= end_date)
    
    results = query.group_by(User.username).all()
    
    return [
        StaffPerformanceResponse(
            staff_name=result.staff_name,
            transaction_count=result.transaction_count or 0,
            total_revenue=float(result.total_revenue) if result.total_revenue else 0.0
        )
        for result in results
    ]
