from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, User
from ..schemas.parking import CustomerCreate
from ..security import get_current_user, require_admin, require_employee_or_admin

router = APIRouter(prefix="/api/customers", tags=["Customers"])


@router.get("/me")
def get_my_customer_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    customer = (
        db.query(Customer)
        .filter(Customer.user_id == current_user.id)
        .first()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Chưa có hồ sơ khách hàng")
    return customer


@router.get("/")
def list_customers(
    db: Session = Depends(get_db),
    current_user=Depends(require_employee_or_admin),
):
    return db.query(Customer).order_by(Customer.id).all()


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    if db.query(Customer).filter(Customer.customer_code == payload.customer_code).first():
        raise HTTPException(status_code=400, detail="Mã khách hàng đã tồn tại")

    customer = Customer(**payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer
