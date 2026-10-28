from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import (
    User,
    Employee,
    Area,
    Customer,
    ParkingArea,
    ParkingSlot,
    Vehicle,
    ParkingTicket,
    Payment,
    PriceRule,
    Pricing,
    ActivityLog,
    Notification,
)
from .security import (
    canonical_role,
    get_current_user,
    require_admin,
    require_employee,
    require_employee_or_admin,
)
from .routers import auth
from .routers.ai import router as ai_router
from .routers.customers import router as customers_router
from .routers.employees import router as employees_router
from .routers.parking import router as parking_router
from .routers.reports import router as reports_router
from .routers.users import router as users_router
from .routers.tickets import router as tickets_router
from .services.ai import (
    NotConfiguredAiProvider,
    answer_question,
    get_capabilities,
)
from .services.qr import ticket_qr_payload
from .time_utils import VIETNAM_TIMEZONE, to_vietnam_datetime


# =========================================================
# DATABASE
# =========================================================

Base.metadata.create_all(bind=engine)
if "user_id" not in {
    column["name"] for column in inspect(engine).get_columns("customers")
}:
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE customers "
                "ADD COLUMN user_id INTEGER REFERENCES users(id)"
            )
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_customers_user_id ON customers (user_id)"
            )
        )


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(
    title="Parking Management System",
    description="Hệ thống quản lý bãi đỗ xe",
    version="1.0.0",
)


# =========================================================
# TEMPLATE
# =========================================================

templates = Jinja2Templates(directory="templates")


# =========================================================
# AUTH
# =========================================================

app.include_router(auth.router)
app.include_router(customers_router)
app.include_router(employees_router)
app.include_router(users_router)
app.include_router(parking_router)
app.include_router(tickets_router)
app.include_router(reports_router)
app.include_router(ai_router)


# =========================================================
# SCHEMAS
# =========================================================

class AreaCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    vehicle_type: str = "MIXED"
    capacity: int = 0


class AreaUpdate(BaseModel):
    name: str
    description: Optional[str] = ""
    vehicle_type: str = "MIXED"
    capacity: int = 0


class SlotCreate(BaseModel):
    slot_code: str
    area_id: int
    status: str = "available"


class SlotUpdate(BaseModel):
    slot_code: str
    status: str


class VehicleCreate(BaseModel):
    customer_id: Optional[int] = None
    license_plate: str
    vehicle_type: str
    owner_name: Optional[str] = ""


class VehicleUpdate(BaseModel):
    customer_id: Optional[int] = None
    license_plate: str
    vehicle_type: str
    owner_name: Optional[str] = ""


class CustomerVehicleRegistration(BaseModel):
    license_plate: str
    vehicle_type: str
    brand: Optional[str] = None
    color: Optional[str] = None


class PriceCreate(BaseModel):
    vehicle_type: str
    from_minute: int
    to_minute: int
    price: float
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    status: str = "ACTIVE"


class PriceUpdate(BaseModel):
    vehicle_type: str
    from_minute: int
    to_minute: int
    price: float
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    status: str = "ACTIVE"


class TicketEntry(BaseModel):
    vehicle_id: int
    slot_id: int


class TicketExit(BaseModel):
    ticket_id: int


class AiQuery(BaseModel):
    question: str


# =========================================================
# HELPER
# =========================================================

def check_user(current_user):
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail="Chưa đăng nhập",
        )

    return current_user


VEHICLE_TYPE_ALIASES = {
    "car": "CAR",
    "ô tô": "CAR",
    "oto": "CAR",
    "motorbike": "MOTORBIKE",
    "motorcycle": "MOTORBIKE",
    "xe máy": "MOTORBIKE",
    "truck": "TRUCK",
    "xe tải": "TRUCK",
    "bus": "BUS",
    "xe buýt": "BUS",
    "ev": "EV",
    "xe điện": "EV",
}


def canonical_vehicle_type(value: str) -> str:
    normalized = (value or "").strip()
    return VEHICLE_TYPE_ALIASES.get(normalized.lower(), normalized.upper())


def log_activity(
    db: Session,
    current_user: User,
    action: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    details: str = "",
    request: Optional[Request] = None,
):
    db.add(
        ActivityLog(
            user_id=current_user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details[:1000],
            ip_address=request.client.host if request and request.client else None,
        )
    )


def log_notification(
    db: Session,
    title: str,
    message: str,
    level: str = "info",
    user_id: Optional[int] = None,
):
    db.add(
        Notification(
            user_id=user_id,
            title=title,
            message=message,
            level=level,
        )
    )


async def read_body(request: Request):
    """
    Nhận được cả:
    - application/json
    - application/x-www-form-urlencoded
    """

    content_type = request.headers.get("content-type", "").lower()

    if "application/json" in content_type:
        return await request.json()

    form = await request.form()

    return dict(form)


def normalize_slot_status(value):
    if value is None:
        return "available"

    normalized = str(value).strip().lower()
    mapping = {
        "empty": "available",
        "available": "available",
        "occupied": "occupied",
        "reserved": "reserved",
        "inactive": "inactive",
        "maintenance": "inactive",
        "unavailable": "inactive",
        "vacant": "available",
    }
    return mapping.get(normalized, normalized)


def normalize_slot_db_status(value):
    if value is None:
        return "EMPTY"

    normalized = str(value).strip().upper()
    mapping = {
        "AVAILABLE": "EMPTY",
        "EMPTY": "EMPTY",
        "VACANT": "EMPTY",
        "OCCUPIED": "OCCUPIED",
        "RESERVED": "RESERVED",
        "INACTIVE": "MAINTENANCE",
        "MAINTENANCE": "MAINTENANCE",
        "UNAVAILABLE": "MAINTENANCE",
    }
    return mapping.get(normalized, normalized)


def normalize_ticket_status(value):
    if value is None:
        return "PARKING"

    normalized = str(value).strip().upper()
    mapping = {
        "ACTIVE": "PARKING",
        "PARKING": "PARKING",
        "PAID": "PAID",
        "COMPLETED": "PAID",
        "FINISHED": "PAID",
        "CANCELLED": "CANCELLED",
        "CANCELED": "CANCELLED",
    }
    return mapping.get(normalized, normalized)


def area_to_dict(area):
    return {
        "id": area.id,
        "area_code": area.area_code,
        "name": getattr(area, "area_name", getattr(area, "name", "")) or "",
        "vehicle_type": area.vehicle_type,
        "capacity": area.capacity,
        "status": area.status,
        "description": getattr(area, "description", "") or "",
    }


def slot_to_dict(slot):
    active_ticket = next(
        (
            ticket
            for ticket in slot.tickets
            if str(getattr(ticket, "status", "")).lower() in {"parking", "parked", "active"}
        ),
        None,
    )

    entry_time = getattr(active_ticket, "check_in", None) or getattr(active_ticket, "entry_time", None)
    return {
        "id": slot.id,
        "slot_code": slot.slot_code,
        "status": normalize_slot_status(slot.status),
        "area_id": slot.area_id,
        "area_name": slot.area.area_name if slot.area else "",
        "vehicle_id": getattr(active_ticket, "vehicle_id", None),
        "license_plate": (
            active_ticket.vehicle.license_plate
            if active_ticket and getattr(active_ticket, "vehicle", None)
            else ""
        ),
        "vehicle_type": (
            active_ticket.vehicle.vehicle_type
            if active_ticket and getattr(active_ticket, "vehicle", None)
            else ""
        ),
        "entry_time": (
            entry_time.strftime("%Y-%m-%d %H:%M:%S")
            if entry_time
            else ""
        ),
    }


def vehicle_to_dict(vehicle):
    active_ticket = next(
        (
            ticket
            for ticket in vehicle.tickets
            if str(getattr(ticket, "status", "")).lower() in {"parking", "parked", "active"}
        ),
        None,
    )
    owner_name = getattr(vehicle, "owner_name", "") or ""
    customer_name = getattr(vehicle.customer, "full_name", None) or owner_name

    entry_time = getattr(active_ticket, "check_in", None) or getattr(active_ticket, "entry_time", None)
    return {
        "id": vehicle.id,
        "customer_id": getattr(vehicle, "customer_id", None),
        "license_plate": vehicle.license_plate,
        "vehicle_type": canonical_vehicle_type(vehicle.vehicle_type),
        "owner_name": owner_name,
        "customer_name": customer_name,
        "status": "parking" if active_ticket else "outside",
        "slot_code": (
            active_ticket.slot.slot_code
            if active_ticket and getattr(active_ticket, "slot", None)
            else ""
        ),
        "entry_time": (
            entry_time.strftime("%Y-%m-%d %H:%M:%S")
            if entry_time
            else ""
        ),
    }


def get_or_create_customer_for_vehicle(
    db: Session,
    owner_name: Optional[str] = None,
    customer_id: Optional[int] = None,
) -> Customer:
    if customer_id is not None:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer is None:
            raise HTTPException(
                status_code=404,
                detail="Khách hàng được chọn không tồn tại",
            )
        return customer

    name = (owner_name or "").strip()
    customer = None
    if name:
        customer = db.query(Customer).filter(Customer.full_name.ilike(name)).first()
    if customer is None:
        if not name:
            raise HTTPException(
                status_code=400,
                detail="Phải chọn khách hàng cho phương tiện",
            )
        customer = Customer(
            customer_code=f"CUST-{uuid4().hex[:10].upper()}",
            full_name=name,
            phone="",
            email="",
            address="",
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
    elif name and customer.full_name != name:
        customer.full_name = name
        db.commit()
    return customer


def price_to_dict(price):
    return {
        "id": price.id,
        "vehicle_type": canonical_vehicle_type(price.vehicle_type),
        "from_minute": price.from_minute,
        "to_minute": price.to_minute,
        "price": price.price,
        "effective_from": price.effective_from.isoformat() if price.effective_from else None,
        "effective_to": price.effective_to.isoformat() if price.effective_to else None,
        "status": price.status,
    }


def calculate_pricing_fee(
    db: Session,
    vehicle_type: str,
    check_in: datetime,
    check_out: datetime,
) -> float:
    now = datetime.utcnow()
    normalized_type = canonical_vehicle_type(vehicle_type)
    rules = (
        db.query(Pricing)
        .filter(
            Pricing.vehicle_type == normalized_type,
            Pricing.status == "ACTIVE",
            Pricing.effective_from <= now,
        )
        .order_by(Pricing.from_minute.desc())
        .all()
    )
    rules = [
        rule for rule in rules
        if rule.effective_to is None or rule.effective_to >= now
    ]
    if not rules:
        raise HTTPException(
            status_code=400,
            detail=f"Chưa có bảng giá đang áp dụng cho loại xe {normalized_type}",
        )

    elapsed_minutes = max(1, int((check_out - check_in).total_seconds() // 60))
    selected_rule = next(
        (
            rule for rule in rules
            if rule.from_minute <= elapsed_minutes
            and (rule.to_minute == 0 or elapsed_minutes <= rule.to_minute)
        ),
        None,
    )
    if selected_rule is None:
        final_rule = max(rules, key=lambda rule: rule.to_minute)
        if final_rule.to_minute != 0 and elapsed_minutes > final_rule.to_minute:
            selected_rule = final_rule
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Chưa có khung giá cho thời lượng gửi xe {elapsed_minutes} phút",
            )
    return float(selected_rule.price)


def ticket_to_dict(ticket):
    entry_dt = getattr(ticket, "check_in", None) or getattr(ticket, "entry_time", None)
    exit_dt = getattr(ticket, "check_out", None) or getattr(ticket, "exit_time", None)
    duration_minutes = None
    if entry_dt:
        end_time = exit_dt or datetime.now()
        duration_minutes = max(
            0,
            int((end_time - entry_dt).total_seconds() // 60),
        )

    return {
        "id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "vehicle_id": ticket.vehicle_id,
        "slot_id": ticket.slot_id,
        "vehicle": (
            ticket.vehicle.license_plate
            if ticket.vehicle
            else ""
        ),
        "vehicle_type": (
            ticket.vehicle.vehicle_type
            if ticket.vehicle
            else ""
        ),
        "slot": (
            ticket.slot.slot_code
            if ticket.slot
            else ""
        ),
        "entry_time": (
            entry_dt.strftime("%Y-%m-%d %H:%M:%S")
            if entry_dt
            else ""
        ),
        "exit_time": (
            exit_dt.strftime("%Y-%m-%d %H:%M:%S")
            if exit_dt
            else ""
        ),
        "fee": getattr(ticket, "fee", None) or getattr(ticket, "amount", None) or 0,
        "status": normalize_ticket_status(ticket.status),
        "duration_minutes": duration_minutes,
    }


# =========================================================
# PAGES
# =========================================================

@app.get("/", response_class=HTMLResponse)
def root_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
    )


@app.get("/parking", response_class=HTMLResponse)
def parking_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="parking.html",
    )


# =========================================================
# HEALTH
# =========================================================

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "database": "connected",
    }


@app.get("/api/ai/capabilities")
def ai_capabilities(
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)
    return {"capabilities": get_capabilities()}


@app.post("/api/ai/query", status_code=501)
def ai_query(
    data: AiQuery,
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)
    if not data.question.strip():
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống")

    try:
        NotConfiguredAiProvider().answer(data.question, {})
    except RuntimeError as error:
        raise HTTPException(status_code=501, detail=str(error))


@app.post("/api/ai/assistant")
def ai_assistant(
    data: AiQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)
    if canonical_role(current_user.role) not in {"CUSTOMER", "ADMIN"}:
        raise HTTPException(status_code=403, detail="Chỉ khách hàng mới được hỏi AI")
    try:
        return answer_question(db, data.question)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except LookupError as error:
        raise HTTPException(status_code=422, detail=str(error))


@app.get("/api/audit-logs")
def get_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    limit = min(max(limit, 1), 500)
    logs = db.query(ActivityLog).order_by(
        ActivityLog.created_at.desc()
    ).limit(limit).all()

    return [
        {
            "id": log.id,
            "username": log.user.username if log.user else "system",
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "details": log.details or "",
            "ip_address": log.ip_address or "",
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


@app.get("/api/notifications")
def get_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Notification).filter(
        (Notification.user_id == current_user.id)
        | (Notification.user_id.is_(None))
    )
    if unread_only:
        query = query.filter(Notification.is_read == 0)

    return [
        {
            "id": notification.id,
            "level": notification.level,
            "title": notification.title,
            "message": notification.message,
            "is_read": bool(notification.is_read),
            "created_at": notification.created_at.isoformat(),
        }
        for notification in query.order_by(
            Notification.created_at.desc()
        ).limit(100).all()
    ]


@app.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        (Notification.user_id == current_user.id)
        | (Notification.user_id.is_(None)),
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông báo")

    notification.is_read = 1
    db.commit()
    return {"message": "Đã đánh dấu thông báo đã đọc"}


# =========================================================
# KHU VỰC
# =========================================================

@app.get("/api/areas/")
def get_areas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)

    areas = (
        db.query(Area)
        .order_by(Area.id)
        .all()
    )

    return [area_to_dict(a) for a in areas]


@app.post("/api/areas/")
async def create_area(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    body = await read_body(request)

    try:
        capacity = int(body.get("capacity", 0))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Sức chứa phải là số nguyên không âm",
        )

    data = AreaCreate(
        name=str(body.get("name", "")),
        description=str(body.get("description", "")),
        vehicle_type=str(body.get("vehicle_type", "MIXED")),
        capacity=capacity,
    )

    name = data.name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Tên khu vực không được để trống",
        )

    if data.capacity < 0:
        raise HTTPException(
            status_code=400,
            detail="Sức chứa không được âm",
        )

    area = Area(
        area_code=f"AREA-{uuid4().hex[:8].upper()}",
        area_name=name,
        vehicle_type=data.vehicle_type.strip().upper() or "MIXED",
        capacity=data.capacity,
        description=data.description or "",
    )

    db.add(area)
    db.commit()
    db.refresh(area)

    return area_to_dict(area)


@app.put("/api/areas/{area_id}")
async def update_area(
    area_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    area = (
        db.query(Area)
        .filter(Area.id == area_id)
        .first()
    )

    if not area:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy khu vực",
        )

    body = await read_body(request)

    try:
        capacity = int(body.get("capacity", area.capacity))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Sức chứa phải là số nguyên không âm",
        )

    data = AreaUpdate(
        name=str(body.get("name", "")),
        description=str(body.get("description", "")),
        vehicle_type=str(body.get("vehicle_type", area.vehicle_type)),
        capacity=capacity,
    )

    name = data.name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Tên khu vực không được để trống",
        )

    if data.capacity < 0:
        raise HTTPException(
            status_code=400,
            detail="Sức chứa không được âm",
        )

    area.area_name = name
    area.vehicle_type = data.vehicle_type.strip().upper() or area.vehicle_type
    area.capacity = data.capacity
    area.description = data.description or ""

    db.commit()
    db.refresh(area)

    return area_to_dict(area)


@app.delete("/api/areas/{area_id}")
def delete_area(
    area_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    area = (
        db.query(Area)
        .filter(Area.id == area_id)
        .first()
    )

    if not area:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy khu vực",
        )

    if any(slot.tickets for slot in area.slots):
        raise HTTPException(
            status_code=400,
            detail="Không thể xóa khu vực đã có lịch sử vé xe",
        )

    for slot in area.slots:
        db.delete(slot)
    db.delete(area)
    db.commit()

    return {
        "message": "Đã xóa khu vực"
    }


# =========================================================
# VỊ TRÍ
# =========================================================

@app.get("/api/areas/{area_id}/slots")
def get_slots(
    area_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)

    slots = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.area_id == area_id)
        .order_by(ParkingSlot.id)
        .all()
    )

    return [slot_to_dict(s) for s in slots]


@app.post("/api/slots/")
async def create_slot(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    body = await read_body(request)

    try:
        area_id = int(body.get("area_id"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="area_id không hợp lệ",
        )

    data = SlotCreate(
        slot_code=str(body.get("slot_code", "")),
        area_id=area_id,
        status=str(body.get("status", "available")),
    )

    area = (
        db.query(Area)
        .filter(Area.id == data.area_id)
        .first()
    )

    if not area:
        raise HTTPException(
            status_code=404,
            detail="Khu vực không tồn tại",
        )

    code = data.slot_code.strip().upper()

    if not code:
        raise HTTPException(
            status_code=400,
            detail="Mã vị trí không được để trống",
        )

    exists = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.slot_code == code)
        .first()
    )

    if exists:
        raise HTTPException(
            status_code=400,
            detail="Mã vị trí đã tồn tại",
        )

    normalized_status = normalize_slot_db_status(data.status)
    if normalized_status not in [
        "EMPTY",
        "OCCUPIED",
        "RESERVED",
        "MAINTENANCE",
    ]:
        raise HTTPException(
            status_code=400,
            detail="Trạng thái không hợp lệ",
        )

    slot = ParkingSlot(
        slot_code=code,
        area_id=data.area_id,
        status=normalized_status,
    )

    db.add(slot)
    db.commit()
    db.refresh(slot)

    return slot_to_dict(slot)


@app.get("/api/slots/{slot_id}")
def get_slot_detail(
    slot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)
    slot = db.query(ParkingSlot).filter(ParkingSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Không tìm thấy vị trí")
    return slot_to_dict(slot)


@app.put("/api/areas/slots/{slot_id}")
async def update_slot(
    slot_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    slot = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.id == slot_id)
        .first()
    )

    if not slot:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy vị trí",
        )

    body = await read_body(request)

    data = SlotUpdate(
        slot_code=str(body.get("slot_code", "")),
        status=str(body.get("status", "")),
    )

    code = data.slot_code.strip().upper()

    exists = (
        db.query(ParkingSlot)
        .filter(
            ParkingSlot.slot_code == code,
            ParkingSlot.id != slot_id,
        )
        .first()
    )

    if exists:
        raise HTTPException(
            status_code=400,
            detail="Mã vị trí đã tồn tại",
        )

    normalized_status = normalize_slot_db_status(data.status)
    if normalized_status not in [
        "EMPTY",
        "OCCUPIED",
        "RESERVED",
        "MAINTENANCE",
    ]:
        raise HTTPException(
            status_code=400,
            detail="Trạng thái không hợp lệ",
        )

    slot.slot_code = code
    slot.status = normalized_status

    db.commit()
    db.refresh(slot)

    return slot_to_dict(slot)


@app.delete("/api/slots/{slot_id}")
def delete_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    slot = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.id == slot_id)
        .first()
    )

    if not slot:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy vị trí",
        )

    if slot.tickets:
        raise HTTPException(
            status_code=400,
            detail="Không thể xóa vị trí đã được sử dụng trong lịch sử vé",
        )

    db.delete(slot)
    db.commit()

    return {
        "message": "Đã xóa vị trí"
    }


# =========================================================
# PHƯƠNG TIỆN
# =========================================================

@app.get("/api/vehicles/")
def get_vehicles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)

    vehicle_query = db.query(Vehicle)
    if canonical_role(current_user.role) == "CUSTOMER":
        customer = (
            db.query(Customer)
            .filter(Customer.user_id == current_user.id)
            .first()
        )
        if customer is None:
            return []
        vehicle_query = vehicle_query.filter(Vehicle.customer_id == customer.id)
    elif canonical_role(current_user.role) not in {"ADMIN", "EMPLOYEE"}:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem phương tiện")

    return [
        vehicle_to_dict(vehicle)
        for vehicle in vehicle_query.order_by(Vehicle.id.desc()).all()
    ]


@app.post("/api/vehicles/register", status_code=201)
def register_customer_vehicle(
    payload: CustomerVehicleRegistration,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if canonical_role(current_user.role) != "CUSTOMER":
        raise HTTPException(
            status_code=403,
            detail="Chỉ khách hàng mới được tự đăng ký phương tiện",
        )

    customer = (
        db.query(Customer)
        .filter(Customer.user_id == current_user.id)
        .first()
    )
    if customer is None:
        raise HTTPException(
            status_code=404,
            detail="Tài khoản chưa có hồ sơ khách hàng",
        )

    plate = payload.license_plate.strip().upper()
    vehicle_type = canonical_vehicle_type(payload.vehicle_type)
    if not plate:
        raise HTTPException(status_code=400, detail="Biển số không được để trống")
    if db.query(Vehicle).filter(Vehicle.license_plate == plate).first():
        raise HTTPException(status_code=409, detail="Biển số xe đã được đăng ký")

    vehicle = Vehicle(
        customer_id=customer.id,
        license_plate=plate,
        vehicle_type=vehicle_type,
        brand=payload.brand.strip() if payload.brand else None,
        color=payload.color.strip() if payload.color else None,
    )
    db.add(vehicle)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Biển số xe đã được đăng ký",
        )
    db.refresh(vehicle)
    return vehicle_to_dict(vehicle)


@app.post("/api/vehicles/")
async def create_vehicle(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_employee_or_admin),
):
    check_user(current_user)

    body = await read_body(request)

    data = VehicleCreate(
        customer_id=(body.get("customer_id") or body.get("customerId") or None),
        license_plate=str(body.get("license_plate", "")),
        vehicle_type=str(body.get("vehicle_type", "")),
        owner_name=str(body.get("owner_name", "")),
    )

    plate = data.license_plate.strip().upper()

    if not plate:
        raise HTTPException(
            status_code=400,
            detail="Biển số không được để trống",
        )

    exists = (
        db.query(Vehicle)
        .filter(Vehicle.license_plate == plate)
        .first()
    )

    if exists:
        raise HTTPException(
            status_code=400,
            detail="Biển số xe đã tồn tại",
        )

    customer = get_or_create_customer_for_vehicle(db, data.owner_name, data.customer_id)
    vehicle = Vehicle(
        customer_id=customer.id,
        license_plate=plate,
        vehicle_type=canonical_vehicle_type(data.vehicle_type),
    )

    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    return vehicle_to_dict(vehicle)


@app.put("/api/vehicles/{vehicle_id}")
async def update_vehicle(
    vehicle_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == vehicle_id)
        .first()
    )

    if not vehicle:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy phương tiện",
        )

    body = await read_body(request)

    data = VehicleUpdate(
        customer_id=(body.get("customer_id") or body.get("customerId") or None),
        license_plate=str(body.get("license_plate", "")),
        vehicle_type=str(body.get("vehicle_type", "")),
        owner_name=str(body.get("owner_name", "")),
    )

    plate = data.license_plate.strip().upper()

    exists = (
        db.query(Vehicle)
        .filter(
            Vehicle.license_plate == plate,
            Vehicle.id != vehicle_id,
        )
        .first()
    )

    if exists:
        raise HTTPException(
            status_code=400,
            detail="Biển số xe đã tồn tại",
        )

    customer = get_or_create_customer_for_vehicle(db, data.owner_name, data.customer_id)
    vehicle.license_plate = plate
    vehicle.vehicle_type = canonical_vehicle_type(data.vehicle_type)
    vehicle.customer_id = customer.id

    db.commit()
    db.refresh(vehicle)

    return vehicle_to_dict(vehicle)


@app.delete("/api/vehicles/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == vehicle_id)
        .first()
    )

    if not vehicle:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy phương tiện",
        )

    if vehicle.tickets:
        raise HTTPException(
            status_code=400,
            detail="Không thể xóa phương tiện đã có lịch sử vé xe",
        )

    db.delete(vehicle)
    db.commit()

    return {
        "message": "Đã xóa phương tiện"
    }


# =========================================================
# BẢNG GIÁ
# =========================================================

@app.get("/api/prices/")
def get_prices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)

    prices = (
        db.query(PriceRule)
        .order_by(PriceRule.id)
        .all()
    )

    return [price_to_dict(p) for p in prices]


@app.post("/api/prices/")
async def create_price(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    body = await read_body(request)

    try:
        data = PriceCreate(
            vehicle_type=canonical_vehicle_type(str(body.get("vehicle_type", ""))),
            from_minute=int(body.get("from_minute", 0)),
            to_minute=int(body.get("to_minute", 0)),
            price=float(body.get("price", 0)),
            effective_from=body.get("effective_from") or datetime.utcnow(),
            effective_to=body.get("effective_to") or None,
            status=str(body.get("status", "ACTIVE")).upper(),
        )
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(
            status_code=400,
            detail="Dữ liệu bảng giá không hợp lệ",
        )

    vehicle_type = data.vehicle_type.strip().upper()

    if not vehicle_type:
        raise HTTPException(
            status_code=400,
            detail="Loại xe không được để trống",
        )

    if data.from_minute < 0 or data.to_minute < 0 or data.price < 0:
        raise HTTPException(
            status_code=400,
            detail="Thời gian và đơn giá không được âm",
        )

    if data.to_minute != 0 and data.to_minute < data.from_minute:
        raise HTTPException(
            status_code=400,
            detail="Mốc phút kết thúc phải lớn hơn hoặc bằng mốc bắt đầu",
        )

    if data.status not in {"ACTIVE", "INACTIVE"}:
        raise HTTPException(
            status_code=400,
            detail="Trạng thái bảng giá không hợp lệ",
        )

    exists = (
        db.query(PriceRule)
        .filter(PriceRule.vehicle_type == vehicle_type)
        .filter(PriceRule.from_minute == data.from_minute)
        .filter(PriceRule.to_minute == data.to_minute)
        .filter(PriceRule.status == "ACTIVE")
        .first()
    )

    if exists:
        raise HTTPException(
            status_code=400,
            detail="Khung thời gian này đã có bảng giá đang hoạt động",
        )

    price = PriceRule(
        vehicle_type=vehicle_type,
        from_minute=data.from_minute,
        to_minute=data.to_minute,
        price=data.price,
        effective_from=data.effective_from or datetime.utcnow(),
        effective_to=data.effective_to,
        status=data.status,
    )

    db.add(price)
    db.commit()
    db.refresh(price)

    return price_to_dict(price)


@app.put("/api/prices/{price_id}")
async def update_price(
    price_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    price = (
        db.query(PriceRule)
        .filter(PriceRule.id == price_id)
        .first()
    )

    if not price:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy bảng giá",
        )

    body = await read_body(request)

    try:
        data = PriceUpdate(
            vehicle_type=canonical_vehicle_type(str(body.get("vehicle_type", ""))),
            from_minute=int(body.get("from_minute", 0)),
            to_minute=int(body.get("to_minute", 0)),
            price=float(body.get("price", 0)),
            effective_from=body.get("effective_from") or price.effective_from,
            effective_to=body.get("effective_to") or None,
            status=str(body.get("status", price.status)).upper(),
        )
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(
            status_code=400,
            detail="Dữ liệu bảng giá không hợp lệ",
        )

    vehicle_type = data.vehicle_type.strip().upper()

    exists = (
        db.query(PriceRule)
        .filter(
            PriceRule.vehicle_type == vehicle_type,
            PriceRule.id != price_id,
            PriceRule.from_minute == data.from_minute,
            PriceRule.to_minute == data.to_minute,
            PriceRule.status == "ACTIVE",
        )
        .first()
    )

    if exists:
        raise HTTPException(
            status_code=400,
            detail="Loại xe đã có bảng giá",
        )

    if data.from_minute < 0 or data.to_minute < 0 or data.price < 0:
        raise HTTPException(
            status_code=400,
            detail="Thời gian và đơn giá không được âm",
        )

    if data.to_minute != 0 and data.to_minute < data.from_minute:
        raise HTTPException(
            status_code=400,
            detail="Mốc phút kết thúc phải lớn hơn hoặc bằng mốc bắt đầu",
        )

    if data.status not in {"ACTIVE", "INACTIVE"}:
        raise HTTPException(
            status_code=400,
            detail="Trạng thái bảng giá không hợp lệ",
        )

    price.vehicle_type = vehicle_type
    price.from_minute = data.from_minute
    price.to_minute = data.to_minute
    price.price = data.price
    price.effective_from = data.effective_from or datetime.utcnow()
    price.effective_to = data.effective_to
    price.status = data.status

    db.commit()
    db.refresh(price)

    return price_to_dict(price)


@app.delete("/api/prices/{price_id}")
def delete_price(
    price_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    price = (
        db.query(PriceRule)
        .filter(PriceRule.id == price_id)
        .first()
    )

    if not price:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy bảng giá",
        )

    db.delete(price)
    db.commit()

    return {
        "message": "Đã xóa bảng giá"
    }


# =========================================================
# VÉ XE
# =========================================================

@app.get("/api/tickets/")
def get_tickets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)

    ticket_query = db.query(ParkingTicket)
    if canonical_role(current_user.role) == "CUSTOMER":
        customer = (
            db.query(Customer)
            .filter(Customer.user_id == current_user.id)
            .first()
        )
        if customer is None:
            return []
        ticket_query = (
            ticket_query
            .join(Vehicle, Vehicle.id == ParkingTicket.vehicle_id)
            .filter(Vehicle.customer_id == customer.id)
        )
    elif canonical_role(current_user.role) not in {"ADMIN", "EMPLOYEE"}:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem vé xe")

    tickets = ticket_query.order_by(ParkingTicket.id.desc()).all()

    return [ticket_to_dict(t) for t in tickets]


@app.get("/api/tickets/{ticket_id}/qr")
def get_ticket_qr_payload(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)
    ticket = db.query(ParkingTicket).filter(
        ParkingTicket.id == ticket_id
    ).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Không tìm thấy vé")
    if canonical_role(current_user.role) == "CUSTOMER":
        customer = (
            db.query(Customer)
            .filter(Customer.user_id == current_user.id)
            .first()
        )
        if customer is None or ticket.vehicle.customer_id != customer.id:
            raise HTTPException(status_code=404, detail="Không tìm thấy vé")
    elif canonical_role(current_user.role) not in {"ADMIN", "EMPLOYEE"}:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem vé xe")

    return {
        "format": "parking-ticket-v1",
        "payload": ticket_qr_payload(ticket),
        "renderer": "client-or-provider",
    }


@app.post("/api/tickets/entry")
def vehicle_entry(
    data: TicketEntry,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_employee_or_admin),
):
    check_user(current_user)

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == data.vehicle_id)
        .first()
    )

    if not vehicle:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy phương tiện",
        )

    slot = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.id == data.slot_id)
        .first()
    )

    if not slot:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy vị trí",
        )

    if normalize_slot_db_status(slot.status) != "EMPTY":
        raise HTTPException(
            status_code=400,
            detail="Vị trí này không còn trống",
        )

    active_vehicle_ticket = next(
        (
            ticket
            for ticket in db.query(ParkingTicket)
            .filter(ParkingTicket.vehicle_id == vehicle.id)
            .all()
            if normalize_ticket_status(ticket.status) == "PARKING"
        ),
        None,
    )

    if active_vehicle_ticket:
        raise HTTPException(
            status_code=400,
            detail="Phương tiện này đang ở trong bãi",
        )

    employee = (
        db.query(Employee)
        .filter(
            Employee.user_id == current_user.id,
            Employee.status == "ACTIVE",
        )
        .first()
    )
    if not employee:
        raise HTTPException(
            status_code=400,
            detail="Tài khoản hiện tại chưa được liên kết với hồ sơ nhân viên",
        )

    ticket = ParkingTicket(
        ticket_code=f"TKT-{uuid4().hex[:12].upper()}",
        vehicle_id=vehicle.id,
        slot_id=slot.id,
        employee_id=employee.id,
        check_in=datetime.utcnow(),
        amount=0,
        status="PARKING",
    )

    slot.status = "OCCUPIED"

    db.add(ticket)
    db.flush()
    log_activity(
        db,
        current_user,
        "ticket.entry",
        "ticket",
        entity_id=ticket.id,
        details=f"Xe {vehicle.license_plate} vào vị trí {slot.slot_code}",
        request=request,
    )
    log_notification(
        db,
        "Xe vào bãi",
        f"{vehicle.license_plate} đang ở vị trí {slot.slot_code}",
        level="success",
    )
    db.commit()
    db.refresh(ticket)

    return ticket_to_dict(ticket)


@app.post("/api/tickets/exit")
def vehicle_exit(
    data: TicketExit,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_employee_or_admin),
):
    check_user(current_user)

    ticket = (
        db.query(ParkingTicket)
        .filter(ParkingTicket.id == data.ticket_id)
        .first()
    )

    if not ticket:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy vé",
        )

    now = datetime.utcnow()

    if normalize_ticket_status(ticket.status) != "PARKING":
        raise HTTPException(
            status_code=400,
            detail="Vé này đã được xe ra",
        )

    employee = (
        db.query(Employee)
        .filter(
            Employee.user_id == current_user.id,
            Employee.status == "ACTIVE",
        )
        .first()
    )
    if not employee:
        raise HTTPException(
            status_code=400,
            detail="Tài khoản hiện tại chưa được liên kết với hồ sơ nhân viên",
        )

    if db.query(Payment).filter(Payment.ticket_id == ticket.id).first():
        raise HTTPException(
            status_code=400,
            detail="Vé này đã có thanh toán",
        )

    fee = calculate_pricing_fee(
        db,
        ticket.vehicle.vehicle_type,
        ticket.check_in,
        now,
    )

    ticket.check_out = now
    ticket.amount = fee
    ticket.status = "PAID"

    slot = db.query(ParkingSlot).filter(ParkingSlot.id == ticket.slot_id).first()
    if slot:
        slot.status = "EMPTY"

    payment = Payment(
        ticket_id=ticket.id,
        payment_method="CASH",
        amount=fee,
        paid_at=now,
        employee_id=employee.id,
        status="PAID",
    )
    db.add(payment)

    log_activity(
        db,
        current_user,
        "ticket.exit",
        "ticket",
        entity_id=ticket.id,
        details=f"Vé {ticket.ticket_code} hoàn tất, phí {fee}",
        request=request,
    )
    log_notification(
        db,
        "Xe ra khỏi bãi",
        f"Vé {ticket.ticket_code} đã hoàn tất, phí {fee:,.0f} đ",
        level="success",
    )
    db.commit()
    db.refresh(ticket)

    return ticket_to_dict(ticket)


# =========================================================
# DOANH THU
# =========================================================

def get_revenue_data(db: Session):
    now = datetime.now(VIETNAM_TIMEZONE)
    today = now.date()
    week_start = today - timedelta(days=6)
    month_start = today.replace(day=1)

    completed = [
        (ticket, to_vietnam_datetime(ticket.exit_time))
        for ticket in db.query(ParkingTicket).all()
        if normalize_ticket_status(ticket.status) == "PAID" and ticket.exit_time is not None
    ]

    def in_range(local_exit_time, start_date):
        return local_exit_time.date() >= start_date

    def total_for(start_date=None):
        return sum(
            float(ticket.fee or 0)
            for ticket, local_exit_time in completed
            if start_date is None or in_range(local_exit_time, start_date)
        )

    by_vehicle_type = {}
    by_day = {}
    trips_by_day = {}

    for ticket, local_exit_time in completed:
        vehicle_type = ticket.vehicle.vehicle_type if ticket.vehicle else "Khác"
        day = local_exit_time.date().isoformat()
        by_vehicle_type[vehicle_type] = (
            by_vehicle_type.get(vehicle_type, 0) + float(ticket.fee or 0)
        )
        by_day[day] = by_day.get(day, 0) + float(ticket.fee or 0)
        trips_by_day[day] = trips_by_day.get(day, 0) + 1

    return {
        "total": total_for(),
        "today": total_for(today),
        "week": total_for(week_start),
        "month": total_for(month_start),
        "tickets": len(completed),
        "by_vehicle_type": [
            {"vehicle_type": key, "revenue": value}
            for key, value in sorted(by_vehicle_type.items())
        ],
        "by_day": [
            {"date": key, "revenue": by_day[key], "trips": trips_by_day[key]}
            for key in sorted(by_day)
        ],
    }


@app.get("/api/revenue")
def get_revenue(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)
    return get_revenue_data(db)


# =========================================================
# DASHBOARD
# =========================================================

def get_dashboard_data(db: Session):
    slots = db.query(ParkingSlot).all()
    total = len(slots)

    available = sum(
        1 for slot in slots if normalize_slot_db_status(slot.status) == "EMPTY"
    )
    occupied = sum(
        1 for slot in slots if normalize_slot_db_status(slot.status) == "OCCUPIED"
    )
    reserved = sum(
        1 for slot in slots if normalize_slot_db_status(slot.status) == "RESERVED"
    )

    total_vehicles = db.query(Vehicle).count()
    all_tickets = db.query(ParkingTicket).all()
    active_tickets = sum(
        1 for ticket in all_tickets if normalize_ticket_status(ticket.status) == "PARKING"
    )
    completed_tickets = sum(
        1 for ticket in all_tickets if normalize_ticket_status(ticket.status) == "PAID"
    )
    revenue = get_revenue_data(db)
    utilization_rate = round(
        ((occupied + reserved) / total * 100) if total else 0,
        2,
    )

    status_distribution = [
        {"status": "available", "count": available},
        {"status": "occupied", "count": occupied},
        {"status": "reserved", "count": reserved},
        {
            "status": "inactive",
            "count": sum(
                1 for slot in slots if normalize_slot_db_status(slot.status) == "MAINTENANCE"
            ),
        },
    ]

    return {
        "total": total,
        "available": available,
        "occupied": occupied,
        "reserved": reserved,
        "total_slots": total,
        "available_slots": available,
        "occupied_slots": occupied,
        "reserved_slots": reserved,
        "total_vehicles": total_vehicles,
        "active_tickets": active_tickets,
        "completed_tickets": completed_tickets,
        "total_trips": active_tickets + completed_tickets,
        "revenue": revenue["total"],
        "total_revenue": revenue["total"],
        "revenue_today": revenue["today"],
        "revenue_week": revenue["week"],
        "revenue_month": revenue["month"],
        "utilization_rate": utilization_rate,
        "revenue_by_vehicle_type": revenue["by_vehicle_type"],
        "revenue_by_day": revenue["by_day"],
        "slot_status_distribution": status_distribution,
    }


@app.get("/api/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)

    dashboard_data = get_dashboard_data(db)
    if canonical_role(current_user.role) != "ADMIN":
        for key in (
            "revenue",
            "total_revenue",
            "revenue_today",
            "revenue_week",
            "revenue_month",
            "revenue_by_vehicle_type",
            "revenue_by_day",
        ):
            dashboard_data.pop(key, None)
    return dashboard_data


# Frontend hiện tại đang gọi /api/dashboard/summary
@app.get("/api/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)

    dashboard_data = get_dashboard_data(db)
    if canonical_role(current_user.role) != "ADMIN":
        for key in (
            "revenue",
            "total_revenue",
            "revenue_today",
            "revenue_week",
            "revenue_month",
            "revenue_by_vehicle_type",
            "revenue_by_day",
        ):
            dashboard_data.pop(key, None)
    return dashboard_data