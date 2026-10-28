from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ParkingArea, ParkingSlot
from ..security import require_admin, require_employee_or_admin

router = APIRouter(prefix="/api/parking", tags=["Parking"])


class ParkingAreaPayload(BaseModel):
    area_code: str
    area_name: str
    vehicle_type: str
    capacity: int = 0
    status: str = "ACTIVE"
    description: str | None = None


class ParkingSlotPayload(BaseModel):
    area_id: int
    slot_code: str
    status: str = "EMPTY"
    floor: int = 1
    row_number: int = 1
    column_number: int = 1


@router.get("/areas")
def list_areas(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    del current_user
    return db.query(ParkingArea).order_by(ParkingArea.id).all()


@router.post("/areas", status_code=status.HTTP_201_CREATED)
def create_area(
    payload: ParkingAreaPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    del current_user
    if not payload.area_code.strip():
        raise HTTPException(status_code=400, detail="area_code không được để trống")
    if not payload.area_name.strip():
        raise HTTPException(status_code=400, detail="area_name không được để trống")

    if db.query(ParkingArea).filter(ParkingArea.area_code == payload.area_code.strip()).first():
        raise HTTPException(status_code=400, detail="Mã khu vực đã tồn tại")

    area = ParkingArea(
        area_code=payload.area_code.strip(),
        area_name=payload.area_name.strip(),
        vehicle_type=payload.vehicle_type.strip(),
        capacity=payload.capacity,
        status=(payload.status or "ACTIVE").upper(),
        description=payload.description,
    )
    db.add(area)
    db.commit()
    db.refresh(area)
    return area


@router.get("/slots")
def list_slots(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    del current_user
    return db.query(ParkingSlot).order_by(ParkingSlot.id).all()


@router.put("/slots/{slot_id}")
def update_slot(
    slot_id: int,
    payload: ParkingSlotPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    del current_user
    slot = db.query(ParkingSlot).filter(ParkingSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Không tìm thấy vị trí đỗ")

    if payload.slot_code:
        slot.slot_code = payload.slot_code.strip()
    if payload.area_id:
        slot.area_id = payload.area_id
    if payload.status:
        slot.status = payload.status.strip().upper()
    if payload.floor is not None:
        slot.floor = payload.floor
    if payload.row_number is not None:
        slot.row_number = payload.row_number
    if payload.column_number is not None:
        slot.column_number = payload.column_number

    db.commit()
    db.refresh(slot)
    return slot
