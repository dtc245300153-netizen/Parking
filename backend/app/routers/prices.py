from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PriceRule
from ..security import require_admin, require_employee_or_admin

router = APIRouter(
    prefix="/api/prices",
    tags=["Prices"]
)


@router.get("/")
def get_prices(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin)
):
    return db.query(PriceRule).all()


@router.post("/", status_code=201)
def create_price(
    vehicle_type: str,
    first_hour_price: float,
    next_hour_price: float,
    monthly_price: float = 0,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    if first_hour_price < 0 or next_hour_price < 0:
        raise HTTPException(400, "Giá không hợp lệ")

    price = PriceRule(
        vehicle_type=vehicle_type,
        first_hour_price=first_hour_price,
        next_hour_price=next_hour_price,
        monthly_price=monthly_price
    )

    db.add(price)
    db.commit()
    db.refresh(price)

    return price


@router.put("/{price_id}")
def update_price(
    price_id: int,
    vehicle_type: str,
    first_hour_price: float,
    next_hour_price: float,
    monthly_price: float = 0,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    price = db.query(PriceRule).filter(
        PriceRule.id == price_id
    ).first()

    if not price:
        raise HTTPException(404, "Không tìm thấy bảng giá")

    price.vehicle_type = vehicle_type
    price.first_hour_price = first_hour_price
    price.next_hour_price = next_hour_price
    price.monthly_price = monthly_price

    db.commit()
    db.refresh(price)

    return price


@router.delete("/{price_id}")
def delete_price(
    price_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin)
):
    price = db.query(PriceRule).filter(
        PriceRule.id == price_id
    ).first()

    if not price:
        raise HTTPException(404, "Không tìm thấy bảng giá")

    db.delete(price)
    db.commit()

    return {"message": "Xóa bảng giá thành công"}