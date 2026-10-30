from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import ParkingSlot, Reservation


RESERVATION_DURATION = timedelta(minutes=30)
ACTIVE_RESERVATION_STATUS = "RESERVED"


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def expire_reservations(
    db: Session,
    now: datetime | None = None,
) -> int:
    """Mark elapsed reservations expired and release their held slots."""
    current_time = now or utc_now_naive()
    expired = (
        db.query(Reservation)
        .filter(
            Reservation.status == ACTIVE_RESERVATION_STATUS,
            Reservation.expire_time <= current_time,
        )
        .all()
    )
    for reservation in expired:
        reservation.status = "EXPIRED"
        if reservation.slot_id is not None:
            slot = (
                db.query(ParkingSlot)
                .filter(ParkingSlot.id == reservation.slot_id)
                .first()
            )
            if slot is not None and str(slot.status).strip().upper() == "RESERVED":
                slot.status = "EMPTY"
    return len(expired)


def reservation_to_dict(reservation: Reservation) -> dict:
    return {
        "id": reservation.id,
        "user_id": reservation.user_id,
        "vehicle_id": reservation.vehicle_id,
        "license_plate": (
            reservation.vehicle.license_plate if reservation.vehicle else None
        ),
        "vehicle_type": (
            reservation.vehicle.vehicle_type if reservation.vehicle else None
        ),
        "slot_id": reservation.slot_id,
        "slot_code": reservation.slot.slot_code if reservation.slot else None,
        "status": reservation.status,
        "reservation_time": reservation.reservation_time.isoformat(),
        "expire_time": reservation.expire_time.isoformat(),
    }
