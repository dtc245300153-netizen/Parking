from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, User
from ..schemas.auth import TokenResponse
from ..security import (
    canonical_role,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


class CustomerRegistration(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=100)
    email: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=30)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_customer(
    payload: CustomerRegistration,
    db: Session = Depends(get_db),
):
    username = payload.username.strip()
    full_name = payload.full_name.strip()
    email = payload.email.strip().lower() if payload.email else None
    email = email or None
    phone = payload.phone.strip() if payload.phone else None

    if len(username) < 3 or not full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tên đăng nhập phải có ít nhất 3 ký tự và họ tên không được để trống",
        )

    duplicate = db.query(User).filter(User.username == username).first()
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tên đăng nhập đã tồn tại",
        )
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email đã được sử dụng",
        )

    user = User(
        username=username,
        password_hash=hash_password(payload.password),
        full_name=full_name,
        email=email,
        phone=phone,
        role="CUSTOMER",
        status="ACTIVE",
    )
    customer = Customer(
        user=user,
        customer_code=f"CUST-{uuid4().hex[:10].upper()}",
        full_name=full_name,
        email=email,
        phone=phone,
    )
    db.add_all([user, customer])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tên đăng nhập hoặc email đã được sử dụng",
        )
    db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "customer_id": customer.id,
    }


@router.post(
    "/login",
    response_model=TokenResponse,
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username).first()

    if (
        user is None
        or str(user.status or "").strip().upper() != "ACTIVE"
        or canonical_role(user.role) not in {"ADMIN", "EMPLOYEE", "CUSTOMER"}
        or not verify_password(form_data.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tài khoản hoặc mật khẩu",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
    })

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.get("/me")
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "email": current_user.email,
        "phone": current_user.phone,
        "role": current_user.role,
        "customer_id": (
            current_user.customer_profile.id
            if current_user.customer_profile
            else None
        ),
    }


@router.post("/logout")
def logout() -> dict:
    return {"message": "Đăng xuất thành công"}
