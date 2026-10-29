from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str = "EMPLOYEE"


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None


class CustomerCreate(BaseModel):
    customer_code: str
    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class VehicleCreate(BaseModel):
    customer_id: int
    license_plate: str
    vehicle_type: str
    brand: Optional[str] = None
    color: Optional[str] = None


class ParkingAreaCreate(BaseModel):
    area_code: str
    area_name: str
    vehicle_type: str
    capacity: int = Field(default=0, ge=0)
    status: str = "ACTIVE"
    description: Optional[str] = None


class ParkingSlotCreate(BaseModel):
    area_id: int
    slot_code: str
    status: str = "EMPTY"
    floor: int = 1
    row_number: int = 1
    column_number: int = 1


class ParkingSlotUpdate(BaseModel):
    slot_code: Optional[str] = None
    status: Optional[str] = None
    floor: Optional[int] = None
    row_number: Optional[int] = None
    column_number: Optional[int] = None


class TicketCheckIn(BaseModel):
    customer_id: Optional[int] = None
    vehicle_id: Optional[int] = None
    license_plate: Optional[str] = None
    area_id: Optional[int] = None
    slot_id: Optional[int] = None
    employee_id: int


class TicketCheckOut(BaseModel):
    ticket_code: Optional[str] = None
    license_plate: Optional[str] = None
    employee_id: int


class PricingCreate(BaseModel):
    vehicle_type: str
    from_minute: int
    to_minute: int
    price: float
    effective_from: datetime
    effective_to: Optional[datetime] = None
    status: str = "ACTIVE"


class PaymentCreate(BaseModel):
    ticket_id: int
    payment_method: str = "CASH"
    amount: float
    employee_id: int
    status: str = "PAID"


class AIChatRequest(BaseModel):
    question: str


class AIChatResponse(BaseModel):
    answer: str
    source: str = "database"
    confidence: str = "high"
