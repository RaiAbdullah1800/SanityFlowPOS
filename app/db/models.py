from sqlalchemy import (
    Column, String, Integer, Float, ForeignKey, DateTime, Enum, Text, JSON
)
from sqlalchemy.dialects.mysql import CHAR, VARCHAR
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from uuid import uuid4
import enum

from .db import Base

import uuid


class UserRole(enum.Enum):
    admin = "admin"
    cashier = "cashier"


class User(Base):
    __tablename__ = "users"

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid4()))
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.cashier)
    created_at = Column(DateTime, server_default=func.now())
    inventory_actions = relationship("InventoryHistory", back_populates="performed_by")
    orders = relationship("Order", back_populates="cashier")


class Item(Base):
    __tablename__ = "items"

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(100), nullable=False)
    image_url = Column(Text, nullable=True)
    category = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())

    sizes = relationship("ItemSize", back_populates="item")
    inventory_histories = relationship("InventoryHistory", back_populates="item")


class ItemSize(Base):
    __tablename__ = "item_sizes"

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid4()))
    item_id = Column(CHAR(36), ForeignKey("items.id"))
    size_label = Column(String(20))  # e.g., Small, Medium, Large
    price = Column(Float, nullable=False)
    discount = Column(Float, nullable=True)  # Optional
    created_at = Column(DateTime, server_default=func.now())

    item = relationship("Item", back_populates="sizes")


class Order(Base):
    __tablename__ = "orders"

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid4()))
    transaction_id = Column(String(100), unique=True, nullable=False)
    date = Column(DateTime, server_default=func.now())
    amount = Column(Float, nullable=False)
    global_discount = Column(Float, default=0.0)
    details = Column(Text, nullable=True)

    cashier_id = Column(CHAR(36), ForeignKey("users.id"))
    cashier = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid4()))
    order_id = Column(CHAR(36), ForeignKey("orders.id"))
    item_id = Column(CHAR(36), ForeignKey("items.id"))
    size_label = Column(String(20))  # To record what size was bought
    quantity = Column(Integer, nullable=False)
    price_at_purchase = Column(Float, nullable=False)
    discount_applied = Column(Float, nullable=True)

    order = relationship("Order", back_populates="items")
    item = relationship("Item")


class InventoryChangeType(enum.Enum):
    sale = "sale"
    restock = "restock"
    correction = "correction"


class InventoryHistory(Base):
    __tablename__ = "inventory_history"

    id = Column(CHAR(36), primary_key=True, default=lambda: str(uuid4()))
    item_id = Column(CHAR(36), ForeignKey("items.id"))
    change = Column(Integer, nullable=False)
    type = Column(Enum(InventoryChangeType), nullable=False)
    description = Column(Text, nullable=True)
    date = Column(DateTime, server_default=func.now())

    performed_by_id = Column(CHAR(36), ForeignKey("users.id"))

    item = relationship("Item", back_populates="inventory_histories")
    performed_by = relationship("User", back_populates="inventory_actions")
