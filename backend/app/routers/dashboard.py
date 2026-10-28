from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    ParkingSlot,
    Vehicle,
    ParkingTicket
)
from ..security import require_admin

router = APIRouter(
    prefix="/api/dashboard",
    tags=["Dashboard"]
)


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


@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    slots = db.query(ParkingSlot).all()
    total_slots = len(slots)

    available_slots = sum(
        1 for slot in slots if normalize_slot_status(slot.status) == "EMPTY"
    )
    occupied_slots = sum(
        1 for slot in slots if normalize_slot_status(slot.status) == "OCCUPIED"
    )
    reserved_slots = sum(
        1 for slot in slots if normalize_slot_status(slot.status) == "RESERVED"
    )

    total_vehicles = db.query(
        Vehicle
    ).count()

    tickets = db.query(ParkingTicket).all()
    active_tickets = sum(
        1 for ticket in tickets if normalize_ticket_status(ticket.status) == "PARKING"
    )
    completed_tickets = sum(
        1 for ticket in tickets if normalize_ticket_status(ticket.status) == "PAID"
    )

    revenue = [
        ticket.amount for ticket in tickets
        if normalize_ticket_status(ticket.status) == "PAID"
    ]

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