from datetime import datetime
from math import ceil
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    ParkingTicket,
    Vehicle,
    ParkingSlot,
    PriceRule
)
from ..security import require_employee_or_admin

router = APIRouter(
    prefix="/api/tickets",
    tags=["Tickets"]
)


def calculate_fee(
    vehicle_type: str,
    entry_time: datetime,
    exit_time: datetime,
    db: Session
):
    price = db.query(PriceRule).filter(
        PriceRule.vehicle_type == vehicle_type
    ).first()

    if not price:
        raise HTTPException(
            400,
            f"Chưa có bảng giá cho loại xe: {vehicle_type}"
        )

    seconds = (exit_time - entry_time).total_seconds()

    hours = max(1, ceil(seconds / 3600))

    if hours == 1:
        return price.first_hour_price

    return (
        price.first_hour_price
        + (hours - 1) * price.next_hour_price
    )


@router.get("/")
def get_tickets(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    return db.query(ParkingTicket).order_by(
        ParkingTicket.id.desc()
    ).all()


@router.get("/active")
def get_active_tickets(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    return db.query(ParkingTicket).filter(
        ParkingTicket.status == "parking"
    ).order_by(ParkingTicket.id.desc()).all()


@router.post("/entry", status_code=201)
def vehicle_entry(
    vehicle_id: int,
    slot_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id
    ).first()

    if not vehicle:
        raise HTTPException(404, "Không tìm thấy phương tiện")

    slot = db.query(ParkingSlot).filter(
        ParkingSlot.id == slot_id
    ).first()

    if not slot:
        raise HTTPException(404, "Không tìm thấy vị trí")

    if slot.status != "available":
        raise HTTPException(
            400,
            "Vị trí này không còn trống"
        )

    active = db.query(ParkingTicket).filter(
        ParkingTicket.vehicle_id == vehicle_id,
        ParkingTicket.status == "parking"
    ).first()

    if active:
        raise HTTPException(
            400,
            "Phương tiện này đang ở trong bãi"
        )

    ticket = ParkingTicket(
        ticket_code="VE-" + uuid.uuid4().hex[:8].upper(),
        vehicle_id=vehicle_id,
        slot_id=slot_id,
        entry_time=datetime.now(),
        status="parking",
        fee=0
    )

    slot.status = "occupied"

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return ticket


@router.post("/{ticket_id}/exit")
def vehicle_exit(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    ticket = db.query(ParkingTicket).filter(
        ParkingTicket.id == ticket_id
    ).first()

    if not ticket:
        raise HTTPException(404, "Không tìm thấy vé")

    if ticket.status != "parking":
        raise HTTPException(
            400,
            "Vé này đã được kết thúc"
        )

    vehicle = db.query(Vehicle).filter(
        Vehicle.id == ticket.vehicle_id
    ).first()

    slot = db.query(ParkingSlot).filter(
        ParkingSlot.id == ticket.slot_id
    ).first()

    exit_time = datetime.now()

    fee = calculate_fee(
        vehicle.vehicle_type,
        ticket.entry_time,
        exit_time,
        db
    )

    ticket.exit_time = exit_time
    ticket.fee = fee
    ticket.status = "completed"

    if slot:
        slot.status = "available"

    db.commit()
    db.refresh(ticket)

    return {
        "message": "Xe đã ra khỏi bãi",
        "ticket": ticket,
        "fee": fee
    }