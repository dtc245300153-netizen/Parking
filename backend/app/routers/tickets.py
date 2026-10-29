from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, Employee, ParkingSlot, ParkingTicket, Payment, Pricing, User, Vehicle
from ..security import canonical_role, get_current_user, require_employee_or_admin

router = APIRouter(prefix="/api/tickets", tags=["Tickets"])


def normalize_slot_status(value):
    normalized = str(value or "").strip().upper()
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
    normalized = str(value or "").strip().upper()
    mapping = {
        "ACTIVE": "PARKING",
        "PARKING": "PARKING",
        "PAID": "PAID",
        "COMPLETED": "PAID",
        "FINISHED": "PAID",
    }
    return mapping.get(normalized, normalized)


class TicketCheckInRequest(BaseModel):
    vehicle_id: int | None = None
    license_plate: str | None = None
    slot_id: int | None = None
    area_id: int | None = None


class TicketCheckOutRequest(BaseModel):
    ticket_code: str | None = None
    license_plate: str | None = None
    payment_method: str = "CASH"


def calculate_fee(db: Session, vehicle_type: str, check_in: datetime, check_out: datetime) -> float:
    elapsed_minutes = max(1, int((check_out - check_in).total_seconds() // 60))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rules = (
        db.query(Pricing)
        .filter(
            Pricing.vehicle_type == vehicle_type,
            Pricing.status == "ACTIVE",
            Pricing.effective_from <= now,
        )
        .order_by(Pricing.from_minute.asc(), Pricing.id.asc())
        .all()
    )
    rules = [
        rule for rule in rules
        if rule.effective_to is None or rule.effective_to >= now
    ]
    if not rules:
        raise HTTPException(
            status_code=400,
            detail=f"Chưa có bảng giá đang hiệu lực cho loại xe {vehicle_type}",
        )

    for rule in rules:
        if rule.from_minute <= elapsed_minutes and (
            rule.to_minute == 0 or elapsed_minutes <= rule.to_minute
        ):
            return float(rule.price)

    last_rule = max(rules, key=lambda rule: rule.to_minute)
    if last_rule.to_minute and elapsed_minutes > last_rule.to_minute:
        return float(last_rule.price)

    raise HTTPException(
        status_code=400,
        detail=f"Chưa cấu hình giá cho thời lượng gửi xe {elapsed_minutes} phút",
    )


@router.get("")
def get_tickets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
    return ticket_query.order_by(ParkingTicket.id.desc()).all()


@router.get("/{ticket_id}")
def get_ticket_by_id(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = db.query(ParkingTicket).filter(ParkingTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Không tìm thấy vé xe")
    if canonical_role(current_user.role) == "CUSTOMER":
        customer = (
            db.query(Customer)
            .filter(Customer.user_id == current_user.id)
            .first()
        )
        if customer is None or ticket.vehicle.customer_id != customer.id:
            raise HTTPException(status_code=404, detail="Không tìm thấy vé xe")
    elif canonical_role(current_user.role) not in {"ADMIN", "EMPLOYEE"}:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem vé xe")
    return ticket


@router.post("/check-in", status_code=status.HTTP_201_CREATED)
def check_in_vehicle(
    payload: TicketCheckInRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    if not payload.vehicle_id and not payload.license_plate:
        raise HTTPException(
            status_code=400,
            detail="Cần cung cấp vehicle_id hoặc biển số xe",
        )

    vehicle_query = db.query(Vehicle)
    if payload.vehicle_id:
        vehicle_query = vehicle_query.filter(Vehicle.id == payload.vehicle_id)
    else:
        vehicle_query = vehicle_query.filter(
            Vehicle.license_plate == payload.license_plate.strip().upper()
        )
    vehicle = vehicle_query.first()
    if vehicle is None:
        raise HTTPException(
            status_code=404,
            detail="Xe chưa được đăng ký trong hệ thống",
        )

    if payload.slot_id is None and payload.area_id is None:
        raise HTTPException(status_code=400, detail="slot_id hoặc area_id phải được cung cấp")

    slot = None
    if payload.slot_id is not None:
        slot = db.query(ParkingSlot).filter(ParkingSlot.id == payload.slot_id).first()
    elif payload.area_id is not None:
        candidates = (
            db.query(ParkingSlot)
            .filter(ParkingSlot.area_id == payload.area_id)
            .order_by(ParkingSlot.id)
            .all()
        )
        slot = next(
            (candidate for candidate in candidates if normalize_slot_status(candidate.status) == "EMPTY"),
            None,
        )

    if not slot:
        raise HTTPException(status_code=400, detail="Không còn chỗ trống phù hợp")

    if payload.area_id is not None and slot.area_id != payload.area_id:
        raise HTTPException(
            status_code=400,
            detail="Vị trí đỗ không thuộc khu vực đã chọn",
        )

    if normalize_slot_status(slot.status) != "EMPTY":
        raise HTTPException(status_code=400, detail="Chỗ đỗ này không còn trống")
    if slot.area and str(slot.area.status).strip().upper() != "ACTIVE":
        raise HTTPException(status_code=400, detail="Khu vực đỗ hiện không hoạt động")

    active_ticket = (
        db.query(ParkingTicket)
        .filter(ParkingTicket.vehicle_id == vehicle.id)
        .order_by(ParkingTicket.id.desc())
        .all()
    )
    active_ticket = next(
        (ticket for ticket in active_ticket if normalize_ticket_status(ticket.status) == "PARKING"),
        None,
    )
    if active_ticket:
        raise HTTPException(status_code=400, detail="Xe này đang trong bãi")

    employee = (
        db.query(Employee)
        .filter(Employee.user_id == current_user.id, Employee.status == "ACTIVE")
        .first()
    )
    if employee is None:
        raise HTTPException(
            status_code=400,
            detail="Tài khoản chưa được liên kết với hồ sơ nhân viên đang hoạt động",
        )

    area_type = (slot.area.vehicle_type if slot.area else "").strip().upper()
    if area_type not in {"", "MIXED", vehicle.vehicle_type.strip().upper()}:
        raise HTTPException(
            status_code=400,
            detail="Loại xe không phù hợp với khu vực đỗ",
        )

    ticket = ParkingTicket(
        ticket_code=f"TKT-{uuid4().hex[:12].upper()}",
        vehicle_id=vehicle.id,
        slot_id=slot.id,
        employee_id=employee.id,
        check_in=datetime.now(timezone.utc).replace(tzinfo=None),
        amount=0,
        status="PARKING",
    )

    slot.status = "OCCUPIED"
    db.add(ticket)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    db.refresh(ticket)
    return {
        "message": "Check-in thành công",
        "ticket": {
            "id": ticket.id,
            "ticket_code": ticket.ticket_code,
            "vehicle_id": ticket.vehicle_id,
            "license_plate": vehicle.license_plate,
            "slot_id": ticket.slot_id,
            "slot_code": slot.slot_code,
            "check_in": ticket.check_in.isoformat(),
            "status": ticket.status,
        },
    }


@router.post("/check-out")
def check_out_vehicle(
    payload: TicketCheckOutRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    if not payload.ticket_code and not payload.license_plate:
        raise HTTPException(
            status_code=400,
            detail="Cần cung cấp mã vé hoặc biển số xe",
        )

    ticket = None

    if payload.ticket_code:
        ticket = (
            db.query(ParkingTicket)
            .filter(ParkingTicket.ticket_code == payload.ticket_code.strip().upper())
            .first()
        )
    elif payload.license_plate:
        candidates = (
            db.query(ParkingTicket)
            .join(Vehicle, Vehicle.id == ParkingTicket.vehicle_id)
            .filter(Vehicle.license_plate == payload.license_plate.strip().upper())
            .order_by(ParkingTicket.id.desc())
            .all()
        )
        ticket = next(
            (item for item in candidates if normalize_ticket_status(item.status) == "PARKING"),
            None,
        )

    if not ticket:
        raise HTTPException(status_code=404, detail="Không tìm thấy vé đang hoạt động")

    if normalize_ticket_status(ticket.status) != "PARKING":
        raise HTTPException(status_code=400, detail="Vé không ở trạng thái đang gửi")

    if ticket.check_in is None:
        raise HTTPException(status_code=400, detail="Thời gian check-in không hợp lệ")

    employee = (
        db.query(Employee)
        .filter(Employee.user_id == current_user.id, Employee.status == "ACTIVE")
        .first()
    )
    if employee is None:
        raise HTTPException(
            status_code=400,
            detail="Tài khoản chưa được liên kết với hồ sơ nhân viên đang hoạt động",
        )

    check_out = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = db.query(Vehicle).filter(Vehicle.id == ticket.vehicle_id).first()
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy phương tiện của vé")

    fee = calculate_fee(db, vehicle.vehicle_type, ticket.check_in, check_out)

    payment_method = payload.payment_method.strip().upper()
    if not payment_method:
        raise HTTPException(status_code=400, detail="Phương thức thanh toán không hợp lệ")

    slot = db.query(ParkingSlot).filter(ParkingSlot.id == ticket.slot_id).first()
    if slot is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy vị trí đỗ của vé")

    payment = Payment(
        ticket_id=ticket.id,
        payment_method=payment_method,
        amount=fee,
        paid_at=check_out,
        employee_id=employee.id,
        status="PAID",
    )
    ticket.check_out = check_out
    ticket.amount = fee
    ticket.status = "PAID"
    slot.status = "EMPTY"
    db.add(payment)

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    db.refresh(ticket)

    return {
        "message": "Check-out thành công",
        "ticket": {
            "id": ticket.id,
            "ticket_code": ticket.ticket_code,
            "vehicle_id": ticket.vehicle_id,
            "license_plate": vehicle.license_plate,
            "slot_id": ticket.slot_id,
            "check_in": ticket.check_in.isoformat(),
            "check_out": check_out.isoformat(),
            "status": ticket.status,
        },
        "amount": fee,
        "payment": {
            "id": payment.id,
            "amount": payment.amount,
            "payment_method": payment.payment_method,
            "status": payment.status,
            "paid_at": payment.paid_at.isoformat(),
        },
    }