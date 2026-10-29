from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Vehicle
from ..security import require_admin, require_employee_or_admin

router = APIRouter(
    prefix="/api/vehicles",
    tags=["Vehicles"]
)


@router.get("/")
def get_vehicles(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    return db.query(Vehicle).order_by(Vehicle.id.desc()).all()


@router.post("/", status_code=201)
def create_vehicle(
    license_plate: str,
    vehicle_type: str,
    owner_name: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    license_plate = license_plate.strip().upper()

    if not license_plate:
        raise HTTPException(400, "Biển số không được để trống")

    existing = db.query(Vehicle).filter(
        Vehicle.license_plate == license_plate
    ).first()

    if existing:
        raise HTTPException(400, "Biển số đã tồn tại")

    vehicle = Vehicle(
        license_plate=license_plate,
        vehicle_type=vehicle_type,
        owner_name=owner_name
    )

    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    return vehicle


@router.put("/{vehicle_id}")
def update_vehicle(
    vehicle_id: int,
    license_plate: str,
    vehicle_type: str,
    owner_name: str = "",
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id
    ).first()

    if not vehicle:
        raise HTTPException(404, "Không tìm thấy phương tiện")

    license_plate = license_plate.strip().upper()

    duplicate = db.query(Vehicle).filter(
        Vehicle.license_plate == license_plate,
        Vehicle.id != vehicle_id
    ).first()

    if duplicate:
        raise HTTPException(400, "Biển số đã tồn tại")

    vehicle.license_plate = license_plate
    vehicle.vehicle_type = vehicle_type
    vehicle.owner_name = owner_name

    db.commit()
    db.refresh(vehicle)

    return vehicle


@router.delete("/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id
    ).first()

    if not vehicle:
        raise HTTPException(404, "Không tìm thấy phương tiện")

    active_ticket = next(
        (t for t in vehicle.tickets if t.status == "parking"),
        None
    )

    if active_ticket:
        raise HTTPException(
            400,
            "Không thể xóa xe đang có vé trong bãi"
        )

    db.delete(vehicle)
    db.commit()

    return {"message": "Xóa phương tiện thành công"}