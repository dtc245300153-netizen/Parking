from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base


# =========================
# 1. NGƯỜI DÙNG
# =========================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="employee")

    def __repr__(self):
        return f"<User {self.username}>"


# =========================
# 2. KHU VỰC
# =========================
class Area(Base):
    __tablename__ = "areas"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)

    slots = relationship(
        "ParkingSlot",
        back_populates="area",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Area {self.name}>"


# =========================
# 3. VỊ TRÍ ĐỖ
# =========================
class ParkingSlot(Base):
    __tablename__ = "parking_slots"

    id = Column(Integer, primary_key=True, index=True)
    slot_code = Column(String(20), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="available")

    area_id = Column(Integer, ForeignKey("areas.id"), nullable=False)

    area = relationship(
        "Area",
        back_populates="slots"
    )

    tickets = relationship(
        "ParkingTicket",
        back_populates="slot"
    )

    def __repr__(self):
        return f"<ParkingSlot {self.slot_code}>"


# =========================
# 4. PHƯƠNG TIỆN
# =========================
class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    license_plate = Column(String(20), unique=True, nullable=False, index=True)
    vehicle_type = Column(String(30), nullable=False)
    owner_name = Column(String(100), nullable=True)

    tickets = relationship(
        "ParkingTicket",
        back_populates="vehicle"
    )

    def __repr__(self):
        return f"<Vehicle {self.license_plate}>"


# =========================
# 5. BẢNG GIÁ
# =========================
class PriceRule(Base):
    __tablename__ = "price_rules"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_type = Column(String(30), nullable=False)
    first_hour_price = Column(Float, nullable=False)
    next_hour_price = Column(Float, nullable=False)
    monthly_price = Column(Float, nullable=True)

    def __repr__(self):
        return f"<PriceRule {self.vehicle_type}>"


# =========================
# 6. VÉ / LƯỢT GỬI XE
# =========================
class ParkingTicket(Base):
    __tablename__ = "parking_tickets"

    id = Column(Integer, primary_key=True, index=True)

    ticket_code = Column(
        String(30),
        unique=True,
        nullable=False,
        index=True
    )

    vehicle_id = Column(
        Integer,
        ForeignKey("vehicles.id"),
        nullable=False
    )

    slot_id = Column(
        Integer,
        ForeignKey("parking_slots.id"),
        nullable=False
    )

    entry_time = Column(
        DateTime,
        nullable=False,
        default=datetime.now
    )

    exit_time = Column(
        DateTime,
        nullable=True
    )

    fee = Column(
        Float,
        nullable=False,
        default=0
    )

    status = Column(
        String(20),
        nullable=False,
        default="parking"
    )

    vehicle = relationship(
        "Vehicle",
        back_populates="tickets"
    )

    slot = relationship(
        "ParkingSlot",
        back_populates="tickets"
    )

    def __repr__(self):
        return f"<ParkingTicket {self.ticket_code}>"