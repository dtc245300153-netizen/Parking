from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship, synonym

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=True)
    phone = Column(String(30), nullable=True)
    role = Column(String(20), nullable=False, default="EMPLOYEE")
    status = Column(String(20), nullable=False, default="ACTIVE")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    employee = relationship("Employee", back_populates="user", uselist=False)
    customer_profile = relationship("Customer", back_populates="user", uselist=False)
    conversations = relationship("AIConversation", back_populates="user")
    ai_logs = relationship("AILog", back_populates="user")
    activity_logs = relationship("ActivityLog", back_populates="user")
    notifications = relationship("Notification", back_populates="user")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    employee_code = Column(String(50), unique=True, nullable=False)
    position = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="ACTIVE")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="employee")
    tickets = relationship("ParkingTicket", back_populates="employee")
    payments = relationship("Payment", back_populates="employee")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=True)
    customer_code = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    phone = Column(String(30), nullable=True)
    email = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="customer_profile")
    vehicles = relationship("Vehicle", back_populates="customer")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    license_plate = Column(String(30), unique=True, nullable=False, index=True)
    vehicle_type = Column(String(30), nullable=False)
    brand = Column(String(50), nullable=True)
    color = Column(String(30), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    customer = relationship("Customer", back_populates="vehicles")
    tickets = relationship("ParkingTicket", back_populates="vehicle")

    @property
    def owner_name(self):
        return self.customer.full_name if self.customer else ""

    @owner_name.setter
    def owner_name(self, value):
        name = (value or "").strip()
        if not name:
            return
        if self.customer is None:
            self.customer = Customer(
                customer_code=f"CUST-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                full_name=name,
                phone="",
                email="",
                address="",
            )
        else:
            self.customer.full_name = name


class ParkingArea(Base):
    __tablename__ = "parking_areas"

    id = Column(Integer, primary_key=True, index=True)
    area_code = Column(String(50), unique=True, nullable=False, index=True)
    area_name = Column(String(100), nullable=False)
    vehicle_type = Column(String(30), nullable=False)
    capacity = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="ACTIVE")
    description = Column(Text, nullable=True)

    slots = relationship("ParkingSlot", back_populates="area")


class ParkingSlot(Base):
    __tablename__ = "parking_slots"

    id = Column(Integer, primary_key=True, index=True)
    area_id = Column(Integer, ForeignKey("parking_areas.id"), nullable=False)
    slot_code = Column(String(50), unique=True, nullable=False, index=True)
    status = Column(String(30), nullable=False, default="EMPTY")
    floor = Column(Integer, nullable=False, default=1)
    row_number = Column(Integer, nullable=False, default=1)
    column_number = Column(Integer, nullable=False, default=1)

    area = relationship("ParkingArea", back_populates="slots")
    tickets = relationship("ParkingTicket", back_populates="slot")


class ParkingTicket(Base):
    __tablename__ = "parking_tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_code = Column(String(50), unique=True, nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    slot_id = Column(Integer, ForeignKey("parking_slots.id"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    check_in = Column(DateTime, nullable=False, default=datetime.utcnow)
    check_out = Column(DateTime, nullable=True)
    amount = Column(Float, nullable=False, default=0)
    status = Column(String(30), nullable=False, default="PARKING")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    exit_time = synonym("check_out")
    fee = synonym("amount")

    vehicle = relationship("Vehicle", back_populates="tickets")
    slot = relationship("ParkingSlot", back_populates="tickets")
    employee = relationship("Employee", back_populates="tickets")
    payment = relationship("Payment", back_populates="ticket", uselist=False)


class Pricing(Base):
    __tablename__ = "pricing"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_type = Column(String(30), nullable=False)
    from_minute = Column(Integer, nullable=False, default=0)
    to_minute = Column(Integer, nullable=False, default=0)
    price = Column(Float, nullable=False)
    effective_from = Column(DateTime, nullable=False)
    effective_to = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="ACTIVE")


# Backward-compatible aliases for the existing project interfaces.
Area = ParkingArea
PriceRule = Pricing


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("parking_tickets.id"), unique=True, nullable=False)
    payment_method = Column(String(30), nullable=False, default="CASH")
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    status = Column(String(20), nullable=False, default="PAID")

    ticket = relationship("ParkingTicket", back_populates="payment")
    employee = relationship("Employee", back_populates="payments")


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="conversations")


class AILog(Base):
    __tablename__ = "ai_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    prompt = Column(Text, nullable=False)
    input_data = Column(Text, nullable=True)
    output_data = Column(Text, nullable=True)
    feedback = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="ai_logs")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=True)
    details = Column(String(1000), nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="activity_logs")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    level = Column(String(20), nullable=False, default="info")
    title = Column(String(120), nullable=False)
    message = Column(String(500), nullable=False)
    is_read = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="notifications")