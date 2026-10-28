from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Employee, ParkingSlot, ParkingTicket, Payment, Pricing, Vehicle
from ..schemas.parking import PaymentCreate, TicketCheckIn, TicketCheckOut
from ..security import require_employee_or_admin

router = APIRouter(prefix="/api/tickets", tags=["Ticketing"])


def calculate_amount(vehicle_type: str, check_in: datetime, check_out: datetime, db: Session) -> float:
    pricing = db.query(Pricing).filter(Pricing.vehicle_type == vehicle_type, Pricing.status == "ACTIVE").order_by(Pricing.id.desc()).first()
    if not pricing:
        raise HTTPException(status_code=400, detail=f"Chưa có bảng giá cho loại xe {vehicle_type}")

    elapsed_minutes = max(1, int((check_out - check_in).total_seconds() // 60))
    if elapsed_minutes <= pricing.from_minute:
        return float(pricing.price)
    return float(pricing.price + ((elapsed_minutes - pricing.from_minute) / max(1, pricing.to_minute - pricing.from_minute)) * pricing.price)


@router.post("/check-in", status_code=status.HTTP_201_CREATED)
def check_in(
    payload: TicketCheckIn,
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    vehicle = None
    if payload.vehicle_id:
        vehicle = db.query(Vehicle).filter(Vehicle.id == payload.vehicle_id).first()
    elif payload.license_plate:
        vehicle = db.query(Vehicle).filter(Vehicle.license_plate == payload.license_plate).first()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Không tìm thấy phương tiện")

    employee = db.query(Employee).filter(Employee.id == payload.employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhân viên")

    slot = None
    if payload.slot_id:
        slot = db.query(ParkingSlot).filter(ParkingSlot.id == payload.slot_id).first()
    elif payload.area_id:
        slot = db.query(ParkingSlot).filter(ParkingSlot.area_id == payload.area_id, ParkingSlot.status == "EMPTY").order_by(ParkingSlot.id).first()

    if not slot:
        raise HTTPException(status_code=400, detail="Không còn chỗ trống phù hợp")

    if db.query(ParkingTicket).filter(ParkingTicket.vehicle_id == vehicle.id, ParkingTicket.status == "PARKING").first():
        raise HTTPException(status_code=400, detail="Xe này đang trong bãi")

    ticket = ParkingTicket(
        ticket_code=f"TICKET-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{vehicle.id}",
        vehicle_id=vehicle.id,
        slot_id=slot.id,
        employee_id=employee.id,
        check_in=datetime.utcnow(),
        amount=0,
        status="PARKING",
    )
    slot.status = "OCCUPIED"
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.post("/check-out")
def check_out(
    payload: TicketCheckOut,
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    ticket = None
    if payload.ticket_code:
        ticket = db.query(ParkingTicket).filter(ParkingTicket.ticket_code == payload.ticket_code).first()
    elif payload.license_plate:
        vehicle = db.query(Vehicle).filter(Vehicle.license_plate == payload.license_plate).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Không tìm thấy phương tiện")
        ticket = db.query(ParkingTicket).filter(ParkingTicket.vehicle_id == vehicle.id, ParkingTicket.status == "PARKING").first()

    if not ticket:
        raise HTTPException(status_code=404, detail="Không tìm thấy vé đang hoạt động")

    if ticket.status != "PARKING":
        raise HTTPException(status_code=400, detail="Vé không ở trạng thái đang gửi")

    check_out_time = datetime.utcnow()
    amount = calculate_amount(ticket.vehicle.vehicle_type, ticket.check_in, check_out_time, db)
    ticket.check_out = check_out_time
    ticket.amount = amount
    ticket.status = "PAID"

    slot = db.query(ParkingSlot).filter(ParkingSlot.id == ticket.slot_id).first()
    if slot:
        slot.status = "EMPTY"

    payment = Payment(
        ticket_id=ticket.id,
        payment_method="CASH",
        amount=amount,
        paid_at=datetime.utcnow(),
        employee_id=payload.employee_id,
        status="PAID",
    )
    db.add(payment)
    db.commit()
    return {"message": "Xe đã ra khỏi bãi", "ticket_code": ticket.ticket_code, "amount": amount}


@router.get("/")
def list_tickets(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    return db.query(ParkingTicket).order_by(ParkingTicket.id.desc()).all()


@router.get("/{ticket_id}")
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    ticket = db.query(ParkingTicket).filter(ParkingTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Không tìm thấy vé")
    return ticket
