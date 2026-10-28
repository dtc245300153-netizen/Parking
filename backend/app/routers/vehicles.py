from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Vehicle
from ..security import require_admin, require_employee_or_admin


router = APIRouter(
    prefix="/api/vehicles",
    tags=["Vehicles"]
)


# =========================
# LẤY DANH SÁCH XE
# =========================
@router.get("/")
def get_vehicles(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    return (
        db.query(Vehicle)
        .order_by(Vehicle.id.desc())
        .all()
    )


# =========================
# THÊM XE
# =========================
@router.post("/", status_code=201)
def create_vehicle(
    license_plate: str = Form(...),
    vehicle_type: str = Form(...),
    owner_name: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    license_plate = license_plate.strip().upper()
    vehicle_type = vehicle_type.strip()
    owner_name = owner_name.strip()

    if not license_plate:
        raise HTTPException(
            status_code=400,
            detail="Biển số không được để trống"
        )

    if not vehicle_type:
        raise HTTPException(
            status_code=400,
            detail="Loại xe không được để trống"
        )

    existing = (
        db.query(Vehicle)
        .filter(Vehicle.license_plate == license_plate)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="Biển số đã tồn tại"
        )

    from ..models import Customer
    customer = db.query(Customer).filter(Customer.full_name.ilike(owner_name)).first() if owner_name else None
    if customer is None and owner_name:
        customer = Customer(
            customer_code=f"CUST-{__import__('datetime').datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            full_name=owner_name,
            phone="",
            email="",
            address="",
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
    if customer is None:
        customer = db.query(Customer).first()
    if customer is None:
        customer = Customer(
            customer_code=f"CUST-{__import__('datetime').datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            full_name="Khách vãng lai",
            phone="",
            email="",
            address="",
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

    vehicle = Vehicle(
        customer_id=customer.id,
        license_plate=license_plate,
        vehicle_type=vehicle_type,
    )

    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    return vehicle


# =========================
# SỬA XE
# =========================
@router.put("/{vehicle_id}")
def update_vehicle(
    vehicle_id: int,
    license_plate: str = Form(...),
    vehicle_type: str = Form(...),
    owner_name: str = Form(""),
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == vehicle_id)
        .first()
    )

    if not vehicle:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy phương tiện"
        )

    license_plate = license_plate.strip().upper()
    vehicle_type = vehicle_type.strip()
    owner_name = owner_name.strip()

    if not license_plate:
        raise HTTPException(
            status_code=400,
            detail="Biển số không được để trống"
        )

    if not vehicle_type:
        raise HTTPException(
            status_code=400,
            detail="Loại xe không được để trống"
        )

    duplicate = (
        db.query(Vehicle)
        .filter(
            Vehicle.license_plate == license_plate,
            Vehicle.id != vehicle_id
        )
        .first()
    )

    if duplicate:
        raise HTTPException(
            status_code=400,
            detail="Biển số đã tồn tại"
        )

    from ..models import Customer
    customer = db.query(Customer).filter(Customer.full_name.ilike(owner_name)).first() if owner_name else None
    if customer is None and owner_name:
        customer = Customer(
            customer_code=f"CUST-{__import__('datetime').datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            full_name=owner_name,
            phone="",
            email="",
            address="",
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)
    if customer is None:
        customer = vehicle.customer or db.query(Customer).first()
    if customer is None:
        customer = Customer(
            customer_code=f"CUST-{__import__('datetime').datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            full_name="Khách vãng lai",
            phone="",
            email="",
            address="",
        )
        db.add(customer)
        db.commit()
        db.refresh(customer)

    vehicle.license_plate = license_plate
    vehicle.vehicle_type = vehicle_type
    vehicle.customer_id = customer.id

    db.commit()
    db.refresh(vehicle)

    return vehicle


# =========================
# XÓA XE
# =========================
@router.delete("/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == vehicle_id)
        .first()
    )

    if not vehicle:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy phương tiện"
        )

    # Không cho xóa xe đang ở trong bãi
    active_ticket = next(
        (
            ticket
            for ticket in vehicle.tickets
            if ticket.status == "parking"
        ),
        None
    )

    if active_ticket:
        raise HTTPException(
            status_code=400,
            detail="Không thể xóa xe đang có vé trong bãi"
        )

    db.delete(vehicle)
    db.commit()

    return {
        "message": "Xóa phương tiện thành công"
    }