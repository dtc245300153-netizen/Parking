from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    ParkingSlot,
    Vehicle,
    ParkingTicket
)
from ..security import require_employee_or_admin

router = APIRouter(
    prefix="/api/dashboard",
    tags=["Dashboard"]
)


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    total_slots = db.query(
        ParkingSlot
    ).count()

    available_slots = db.query(
        ParkingSlot
    ).filter(
        ParkingSlot.status == "available"
    ).count()

    occupied_slots = db.query(
        ParkingSlot
    ).filter(
        ParkingSlot.status == "occupied"
    ).count()

    reserved_slots = db.query(
        ParkingSlot
    ).filter(
        ParkingSlot.status == "reserved"
    ).count()

    total_vehicles = db.query(
        Vehicle
    ).count()

    active_tickets = db.query(
        ParkingTicket
    ).filter(
        ParkingTicket.status == "parking"
    ).count()

    completed_tickets = db.query(
        ParkingTicket
    ).filter(
        ParkingTicket.status == "completed"
    ).count()

    revenue = db.query(
        ParkingTicket
    ).filter(
        ParkingTicket.status == "completed"
    ).with_entities(
        ParkingTicket.fee
    ).all()

    total_revenue = sum(
        item[0] or 0
        for item in revenue
    )

    return {
        "total_slots": total_slots,
        "available_slots": available_slots,
        "occupied_slots": occupied_slots,
        "reserved_slots": reserved_slots,
        "total_vehicles": total_vehicles,
        "active_tickets": active_tickets,
        "completed_tickets": completed_tickets,
        "total_revenue": total_revenue
    }