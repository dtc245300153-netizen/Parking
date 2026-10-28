from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Pricing
from ..schemas.parking import PricingCreate
from ..security import require_admin, require_employee_or_admin

router = APIRouter(prefix="/api/pricing", tags=["Pricing"])


@router.get("/")
def list_pricing(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    return db.query(Pricing).order_by(Pricing.id).all()


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_pricing(
    payload: PricingCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    item = Pricing(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
