from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Area, ParkingSlot
from ..security import require_admin, require_employee_or_admin

router = APIRouter(
    prefix="/api/areas",
    tags=["Areas"]
)


@router.get("/")
def get_areas(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    return db.query(Area).all()


@router.get("/{area_id}")
def get_area(
    area_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    area = db.query(Area).filter(Area.id == area_id).first()

    if not area:
        raise HTTPException(404, "Không tìm thấy khu vực")

    return area


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_area(
    name: str,
    description: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    name = name.strip()

    if not name:
        raise HTTPException(400, "Tên khu vực không được để trống")

    area = Area(
        name=name,
        description=description
    )

    db.add(area)
    db.commit()
    db.refresh(area)

    return area


@router.put("/{area_id}")
def update_area(
    area_id: int,
    name: str,
    description: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    area = db.query(Area).filter(Area.id == area_id).first()

    if not area:
        raise HTTPException(404, "Không tìm thấy khu vực")

    if not name.strip():
        raise HTTPException(400, "Tên khu vực không được để trống")

    area.name = name.strip()
    area.description = description

    db.commit()
    db.refresh(area)

    return area


@router.delete("/{area_id}")
def delete_area(
    area_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    area = db.query(Area).filter(Area.id == area_id).first()

    if not area:
        raise HTTPException(404, "Không tìm thấy khu vực")

    db.delete(area)
    db.commit()

    return {"message": "Xóa khu vực thành công"}


@router.get("/{area_id}/slots")
def get_slots(
    area_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    area = db.query(Area).filter(Area.id == area_id).first()

    if not area:
        raise HTTPException(404, "Không tìm thấy khu vực")

    return db.query(ParkingSlot).filter(
        ParkingSlot.area_id == area_id
    ).all()


@router.post("/{area_id}/slots", status_code=201)
def create_slot(
    area_id: int,
    slot_code: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    area = db.query(Area).filter(Area.id == area_id).first()

    if not area:
        raise HTTPException(404, "Không tìm thấy khu vực")

    slot_code = slot_code.strip().upper()

    if not slot_code:
        raise HTTPException(400, "Mã vị trí không được để trống")

    existing = db.query(ParkingSlot).filter(
        ParkingSlot.slot_code == slot_code
    ).first()

    if existing:
        raise HTTPException(400, "Mã vị trí đã tồn tại")

    slot = ParkingSlot(
        slot_code=slot_code,
        area_id=area_id,
        status="available"
    )

    db.add(slot)
    db.commit()
    db.refresh(slot)

    return slot


@router.put("/slots/{slot_id}")
def update_slot(
    slot_id: int,
    slot_code: str,
    slot_status: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    slot = db.query(ParkingSlot).filter(
        ParkingSlot.id == slot_id
    ).first()

    if not slot:
        raise HTTPException(404, "Không tìm thấy vị trí")

    allowed = ["available", "occupied", "reserved"]

    if slot_status not in allowed:
        raise HTTPException(400, "Trạng thái vị trí không hợp lệ")

    slot_code = slot_code.strip().upper()

    duplicate = db.query(ParkingSlot).filter(
        ParkingSlot.slot_code == slot_code,
        ParkingSlot.id != slot_id
    ).first()

    if duplicate:
        raise HTTPException(400, "Mã vị trí đã tồn tại")

    slot.slot_code = slot_code
    slot.status = slot_status

    db.commit()
    db.refresh(slot)

    return slot


@router.delete("/slots/{slot_id}")
def delete_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    slot = db.query(ParkingSlot).filter(
        ParkingSlot.id == slot_id
    ).first()

    if not slot:
        raise HTTPException(404, "Không tìm thấy vị trí")

    db.delete(slot)
    db.commit()

    return {"message": "Xóa vị trí thành công"}