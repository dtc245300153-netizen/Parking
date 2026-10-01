from datetime import datetime, timedelta
from math import ceil
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import (
    User,
    Area,
    ParkingSlot,
    Vehicle,
    ParkingTicket,
    PriceRule,
    ActivityLog,
    Notification,
)
from .security import get_current_user, require_admin, require_manager_or_admin
from .routers import auth
from .services.ai import (
    NotConfiguredAiProvider,
    answer_question,
    get_capabilities,
)
from .services.qr import ticket_qr_payload


# =========================================================
# DATABASE
# =========================================================

Base.metadata.create_all(bind=engine)


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


# =========================================================
# SCHEMAS
# =========================================================

class AreaCreate(BaseModel):
    name: str
    description: Optional[str] = ""


class AreaUpdate(BaseModel):
    name: str
    description: Optional[str] = ""


class SlotCreate(BaseModel):
    slot_code: str
    area_id: int
    status: str = "available"


class SlotUpdate(BaseModel):
    slot_code: str
    status: str


class VehicleCreate(BaseModel):
    license_plate: str
    vehicle_type: str
    owner_name: Optional[str] = ""


class VehicleUpdate(BaseModel):
    license_plate: str
    vehicle_type: str
    owner_name: Optional[str] = ""


class PriceCreate(BaseModel):
    vehicle_type: str
    first_hour_price: float
    next_hour_price: float
    monthly_price: float


class PriceUpdate(BaseModel):
    vehicle_type: str
    first_hour_price: float
    next_hour_price: float
    monthly_price: float


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
    "car": "Ô tô",
    "motorbike": "Xe máy",
    "truck": "Xe tải",
    "bus": "Xe buýt",
}


def canonical_vehicle_type(value: str) -> str:
    normalized = (value or "").strip()
    return VEHICLE_TYPE_ALIASES.get(normalized.lower(), normalized)


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


def area_to_dict(area):
    return {
        "id": area.id,
        "name": area.name,
        "description": area.description or "",
    }


def slot_to_dict(slot):
    active_ticket = next(
        (
            ticket
            for ticket in slot.tickets
            if ticket.status == "parking"
        ),
        None,
    )

    return {
        "id": slot.id,
        "slot_code": slot.slot_code,
        "status": slot.status,
        "area_id": slot.area_id,
        "area_name": slot.area.name if slot.area else "",
        "vehicle_id": active_ticket.vehicle_id if active_ticket else None,
        "license_plate": (
            active_ticket.vehicle.license_plate
            if active_ticket and active_ticket.vehicle
            else ""
        ),
        "vehicle_type": (
            active_ticket.vehicle.vehicle_type
            if active_ticket and active_ticket.vehicle
            else ""
        ),
        "entry_time": (
            active_ticket.entry_time.strftime("%Y-%m-%d %H:%M:%S")
            if active_ticket and active_ticket.entry_time
            else ""
        ),
    }


def vehicle_to_dict(vehicle):
    active_ticket = next(
        (
            ticket
            for ticket in vehicle.tickets
            if ticket.status == "parking"
        ),
        None,
    )

    return {
        "id": vehicle.id,
        "license_plate": vehicle.license_plate,
        "vehicle_type": vehicle.vehicle_type,
        "owner_name": vehicle.owner_name or "",
        "status": "parking" if active_ticket else "outside",
        "slot_code": (
            active_ticket.slot.slot_code
            if active_ticket and active_ticket.slot
            else ""
        ),
        "entry_time": (
            active_ticket.entry_time.strftime("%Y-%m-%d %H:%M:%S")
            if active_ticket and active_ticket.entry_time
            else ""
        ),
    }


def price_to_dict(price):
    return {
        "id": price.id,
        "vehicle_type": price.vehicle_type,
        "first_hour_price": price.first_hour_price,
        "next_hour_price": price.next_hour_price,
        "monthly_price": price.monthly_price,
    }


def ticket_to_dict(ticket):
    duration_minutes = None
    if ticket.entry_time:
        end_time = ticket.exit_time or datetime.now()
        duration_minutes = max(
            0,
            int((end_time - ticket.entry_time).total_seconds() // 60),
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
            ticket.entry_time.strftime("%Y-%m-%d %H:%M:%S")
            if ticket.entry_time
            else ""
        ),

        "exit_time": (
            ticket.exit_time.strftime("%Y-%m-%d %H:%M:%S")
            if ticket.exit_time
            else ""
        ),

        "fee": ticket.fee or 0,
        "status": ticket.status,
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
    current_user: User = Depends(require_manager_or_admin),
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

    data = AreaCreate(
        name=str(body.get("name", "")),
        description=str(body.get("description", "")),
    )

    name = data.name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Tên khu vực không được để trống",
        )

    area = Area(
        name=name,
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

    data = AreaUpdate(
        name=str(body.get("name", "")),
        description=str(body.get("description", "")),
    )

    name = data.name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Tên khu vực không được để trống",
        )

    area.name = name
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

    if data.status not in [
        "available",
        "occupied",
        "reserved",
        "inactive",
    ]:
        raise HTTPException(
            status_code=400,
            detail="Trạng thái không hợp lệ",
        )

    slot = ParkingSlot(
        slot_code=code,
        area_id=data.area_id,
        status=data.status,
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

    if data.status not in [
        "available",
        "occupied",
        "reserved",
        "inactive",
    ]:
        raise HTTPException(
            status_code=400,
            detail="Trạng thái không hợp lệ",
        )

    slot.slot_code = code
    slot.status = data.status

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

    active_ticket = (
        db.query(ParkingTicket)
        .filter(
            ParkingTicket.slot_id == slot_id,
            ParkingTicket.status == "parking",
        )
        .first()
    )

    if active_ticket:
        raise HTTPException(
            status_code=400,
            detail="Vị trí đang có xe, không thể xóa",
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

    vehicles = (
        db.query(Vehicle)
        .order_by(Vehicle.id.desc())
        .all()
    )

    return [vehicle_to_dict(v) for v in vehicles]


@app.post("/api/vehicles/")
async def create_vehicle(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    check_user(current_user)

    body = await read_body(request)

    data = VehicleCreate(
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

    vehicle = Vehicle(
        license_plate=plate,
        vehicle_type=canonical_vehicle_type(data.vehicle_type),
        owner_name=data.owner_name or "",
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

    vehicle.license_plate = plate
    vehicle.vehicle_type = canonical_vehicle_type(data.vehicle_type)
    vehicle.owner_name = data.owner_name or ""

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

    active_ticket = (
        db.query(ParkingTicket)
        .filter(
            ParkingTicket.vehicle_id == vehicle_id,
            ParkingTicket.status == "parking",
        )
        .first()
    )

    if active_ticket:
        raise HTTPException(
            status_code=400,
            detail="Xe đang ở trong bãi, không thể xóa",
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
            vehicle_type=str(body.get("vehicle_type", "")),
            first_hour_price=float(body.get("first_hour_price", 0)),
            next_hour_price=float(body.get("next_hour_price", 0)),
            monthly_price=float(body.get("monthly_price", 0)),
        )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="Dữ liệu bảng giá không hợp lệ",
        )

    vehicle_type = data.vehicle_type.strip()

    if not vehicle_type:
        raise HTTPException(
            status_code=400,
            detail="Loại xe không được để trống",
        )

    exists = (
        db.query(PriceRule)
        .filter(PriceRule.vehicle_type == vehicle_type)
        .first()
    )

    if exists:
        raise HTTPException(
            status_code=400,
            detail="Loại xe đã có bảng giá",
        )

    price = PriceRule(
        vehicle_type=vehicle_type,
        first_hour_price=data.first_hour_price,
        next_hour_price=data.next_hour_price,
        monthly_price=data.monthly_price,
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
            vehicle_type=str(body.get("vehicle_type", "")),
            first_hour_price=float(body.get("first_hour_price", 0)),
            next_hour_price=float(body.get("next_hour_price", 0)),
            monthly_price=float(body.get("monthly_price", 0)),
        )
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="Dữ liệu bảng giá không hợp lệ",
        )

    vehicle_type = data.vehicle_type.strip()

    exists = (
        db.query(PriceRule)
        .filter(
            PriceRule.vehicle_type == vehicle_type,
            PriceRule.id != price_id,
        )
        .first()
    )

    if exists:
        raise HTTPException(
            status_code=400,
            detail="Loại xe đã có bảng giá",
        )

    price.vehicle_type = vehicle_type
    price.first_hour_price = data.first_hour_price
    price.next_hour_price = data.next_hour_price
    price.monthly_price = data.monthly_price

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

    tickets = (
        db.query(ParkingTicket)
        .order_by(ParkingTicket.id.desc())
        .all()
    )

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
    current_user: User = Depends(get_current_user),
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

    if slot.status != "available":
        raise HTTPException(
            status_code=400,
            detail="Vị trí này không còn trống",
        )

    active_vehicle_ticket = (
        db.query(ParkingTicket)
        .filter(
            ParkingTicket.vehicle_id == vehicle.id,
            ParkingTicket.status == "parking",
        )
        .first()
    )

    if active_vehicle_ticket:
        raise HTTPException(
            status_code=400,
            detail="Phương tiện này đang ở trong bãi",
        )

    ticket_code = (
        "VE"
        + datetime.now().strftime("%Y%m%d%H%M%S")
        + str(vehicle.id)
    )

    ticket = ParkingTicket(
        ticket_code=ticket_code,
        vehicle_id=vehicle.id,
        slot_id=slot.id,
        entry_time=datetime.now(),
        status="parking",
        fee=0,
    )

    slot.status = "occupied"

    db.add(ticket)
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
    current_user: User = Depends(get_current_user),
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

    if ticket.status != "parking":
        raise HTTPException(
            status_code=400,
            detail="Vé này đã được xe ra",
        )

    now = datetime.now()

    hours = ceil(
        max(
            1,
            (now - ticket.entry_time).total_seconds() / 3600,
        )
    )

    vehicle_type = canonical_vehicle_type(ticket.vehicle.vehicle_type)
    price_rule = db.query(PriceRule).filter(
        PriceRule.vehicle_type == vehicle_type
    ).first()

    if price_rule:
        if hours <= 1:
            fee = price_rule.first_hour_price
        else:
            fee = (
                price_rule.first_hour_price
                + (hours - 1)
                * price_rule.next_hour_price
            )
    else:
        fee = 0

    ticket.exit_time = now
    ticket.fee = fee
    ticket.status = "completed"

    ticket.slot.status = "available"

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
    now = datetime.now()
    today = now.date()
    week_start = today - timedelta(days=6)
    month_start = today.replace(day=1)

    completed_query = db.query(ParkingTicket).filter(
        ParkingTicket.status == "completed",
        ParkingTicket.exit_time.is_not(None),
    )
    completed = completed_query.all()

    def in_range(ticket, start_date):
        return ticket.exit_time.date() >= start_date

    def total_for(start_date=None):
        return sum(
            float(ticket.fee or 0)
            for ticket in completed
            if start_date is None or in_range(ticket, start_date)
        )

    by_vehicle_type = {}
    by_day = {}
    trips_by_day = {}

    for ticket in completed:
        vehicle_type = ticket.vehicle.vehicle_type if ticket.vehicle else "Khác"
        day = ticket.exit_time.date().isoformat()
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
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)
    return get_revenue_data(db)


# =========================================================
# DASHBOARD
# =========================================================

def get_dashboard_data(db: Session):
    total = db.query(ParkingSlot).count()

    available = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.status == "available")
        .count()
    )

    occupied = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.status == "occupied")
        .count()
    )

    reserved = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.status == "reserved")
        .count()
    )

    total_vehicles = db.query(Vehicle).count()
    active_tickets = db.query(ParkingTicket).filter(
        ParkingTicket.status == "parking"
    ).count()
    completed_tickets = db.query(ParkingTicket).filter(
        ParkingTicket.status == "completed"
    ).count()
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
            "count": db.query(ParkingSlot)
            .filter(ParkingSlot.status == "inactive")
            .count(),
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

    return get_dashboard_data(db)


# Frontend hiện tại đang gọi /api/dashboard/summary
@app.get("/api/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_user(current_user)

    return get_dashboard_data(db)