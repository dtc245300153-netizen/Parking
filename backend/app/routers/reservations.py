from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Customer,
    ParkingArea,
    ParkingSlot,
    ParkingTicket,
    Reservation,
    User,
    Vehicle,
)
from ..security import canonical_role, get_current_user, require_employee_or_admin
from ..services.reservations import (
    ACTIVE_RESERVATION_STATUS,
    RESERVATION_DURATION,
    expire_reservations,
    reservation_to_dict,
    utc_now_naive,
)

router = APIRouter(prefix="/api/reservations", tags=["Reservations"])


class ReservationCreate(BaseModel):
    vehicle_id: int = Field(gt=0)


def _customer_id(db: Session, user_id: int) -> int:
    customer = (
        db.query(Customer)
        .filter(Customer.user_id == user_id)
        .first()
    )
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tài khoản chưa có hồ sơ khách hàng",
        )
    return customer.id


def _release_slot(db: Session, reservation: Reservation) -> None:
    if reservation.slot_id is None:
        return
    slot = (
        db.query(ParkingSlot)
        .filter(ParkingSlot.id == reservation.slot_id)
        .first()
    )
    if slot is not None and str(slot.status).strip().upper() == "RESERVED":
        slot.status = "EMPTY"


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reservation(
    payload: ReservationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if canonical_role(current_user.role) != "CUSTOMER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ khách hàng mới được đặt chỗ trước",
        )

    customer_id = _customer_id(db, current_user.id)
    now = utc_now_naive()
    expire_reservations(db, now)

    vehicle = (
        db.query(Vehicle)
        .filter(
            Vehicle.id == payload.vehicle_id,
            Vehicle.customer_id == customer_id,
        )
        .first()
    )
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy xe của bạn")

    if (
        db.query(ParkingTicket)
        .filter(
            ParkingTicket.vehicle_id == vehicle.id,
            func.upper(ParkingTicket.status).in_(("PARKING", "ACTIVE")),
            ParkingTicket.check_out.is_(None),
        )
        .first()
    ):
        raise HTTPException(status_code=409, detail="Xe này đang ở trong bãi")

    if (
        db.query(Reservation)
        .filter(
            Reservation.vehicle_id == vehicle.id,
            Reservation.status == ACTIVE_RESERVATION_STATUS,
            Reservation.expire_time > now,
        )
        .first()
    ):
        raise HTTPException(status_code=409, detail="Xe này đã có chỗ đặt trước")

    vehicle_type = vehicle.vehicle_type.strip().upper()
    slot = (
        db.query(ParkingSlot)
        .join(ParkingArea, ParkingArea.id == ParkingSlot.area_id)
        .filter(
            func.upper(ParkingSlot.status).in_(("EMPTY", "AVAILABLE")),
            func.upper(ParkingArea.status) == "ACTIVE",
            or_(
                func.upper(ParkingArea.vehicle_type) == vehicle_type,
                func.upper(ParkingArea.vehicle_type) == "MIXED",
            ),
        )
        .order_by(ParkingSlot.id)
        .with_for_update()
        .first()
    )
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hiện không còn chỗ trống phù hợp để đặt trước",
        )

    slot.status = "RESERVED"
    reservation = Reservation(
        user_id=current_user.id,
        vehicle_id=vehicle.id,
        slot_id=slot.id,
        status=ACTIVE_RESERVATION_STATUS,
        reservation_time=now,
        expire_time=now + RESERVATION_DURATION,
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return reservation_to_dict(reservation)


@router.get("/my")
def get_my_reservations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if canonical_role(current_user.role) != "CUSTOMER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ khách hàng mới được xem đặt chỗ của mình",
        )

    expire_reservations(db)
    db.commit()
    reservations = (
        db.query(Reservation)
        .filter(Reservation.user_id == current_user.id)
        .order_by(Reservation.reservation_time.desc(), Reservation.id.desc())
        .all()
    )
    return [reservation_to_dict(reservation) for reservation in reservations]


@router.get("/active")
def get_active_reservations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_employee_or_admin),
):
    del current_user
    expire_reservations(db)
    db.commit()
    reservations = (
        db.query(Reservation)
        .filter(
            Reservation.status == ACTIVE_RESERVATION_STATUS,
            Reservation.expire_time > utc_now_naive(),
        )
        .order_by(Reservation.expire_time)
        .all()
    )
    return [reservation_to_dict(reservation) for reservation in reservations]


@router.post("/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if canonical_role(current_user.role) != "CUSTOMER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ khách hàng mới được hủy đặt chỗ",
        )

    reservation = (
        db.query(Reservation)
        .filter(
            Reservation.id == reservation_id,
            Reservation.user_id == current_user.id,
        )
        .first()
    )
    if reservation is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy đặt chỗ")

    expire_reservations(db)
    if reservation.status != ACTIVE_RESERVATION_STATUS:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Đặt chỗ này không còn ở trạng thái chờ",
        )

    reservation.status = "CANCELLED"
    _release_slot(db, reservation)
    db.commit()
    return reservation_to_dict(reservation)
