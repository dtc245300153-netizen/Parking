from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customer, Employee, User
from ..schemas.auth import UserResponse
from ..security import hash_password, require_admin, require_employee_or_admin


router = APIRouter(
    prefix="/api/users",
    tags=["Users"],
)


class UserCreateRequest(BaseModel):
    username: str
    password: str
    full_name: str
    email: str | None = None
    phone: str | None = None
    role: str = "EMPLOYEE"
    status: str = "ACTIVE"


class UserUpdateRequest(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str | None = None
    status: str | None = None


def normalize_role(role: str | None) -> str:
    if role is None:
        return "EMPLOYEE"
    normalized = role.strip().upper()
    if normalized in {"ADMIN", "EMPLOYEE", "CUSTOMER"}:
        return normalized
    raise HTTPException(
        status_code=400,
        detail="Role phải là ADMIN, EMPLOYEE hoặc CUSTOMER",
    )


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    del current_user
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    del current_user

    if not payload.username.strip():
        raise HTTPException(status_code=400, detail="username không được để trống")
    if not payload.password:
        raise HTTPException(status_code=400, detail="password không được để trống")
    if not payload.full_name.strip():
        raise HTTPException(status_code=400, detail="full_name không được để trống")

    existing = db.query(User).filter(User.username == payload.username.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tên đăng nhập đã tồn tại")

    role = normalize_role(payload.role)
    user_status = (payload.status or "ACTIVE").strip().upper()
    if user_status not in {"ACTIVE", "INACTIVE"}:
        raise HTTPException(
            status_code=400,
            detail="Trạng thái phải là ACTIVE hoặc INACTIVE",
        )
    email = payload.email.strip().lower() if payload.email else None
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email đã được sử dụng")

    user = User(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        email=email,
        phone=payload.phone.strip() if payload.phone else None,
        role=role,
        status=user_status,
    )

    db.add(user)
    db.flush()
    if role == "EMPLOYEE":
        db.add(
            Employee(
                user_id=user.id,
                employee_code=f"EMP-{uuid4().hex[:8].upper()}",
                position="Nhân viên",
                status=user_status,
            )
        )
    elif role == "CUSTOMER":
        db.add(
            Customer(
                user_id=user.id,
                customer_code=f"CUST-{uuid4().hex[:8].upper()}",
                full_name=user.full_name,
                email=user.email,
                phone=user.phone,
            )
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Tên đăng nhập, email hoặc mã hồ sơ đã được sử dụng",
        )
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")

    if user.id == current_user.id and (
        (payload.role is not None and normalize_role(payload.role) != "ADMIN")
        or (payload.status is not None and payload.status.strip().upper() != "ACTIVE")
    ):
        raise HTTPException(
            status_code=400,
            detail="Không thể tự thay đổi hoặc khóa vai trò quản trị của tài khoản hiện tại",
        )

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
        if not user.full_name:
            raise HTTPException(status_code=400, detail="full_name không được để trống")
    if payload.email is not None:
        user.email = payload.email.strip().lower() or None
    if payload.phone is not None:
        user.phone = payload.phone.strip() or None
    if payload.role is not None:
        user.role = normalize_role(payload.role)
    if payload.status is not None:
        normalized_status = payload.status.strip().upper()
        if normalized_status not in {"ACTIVE", "INACTIVE"}:
            raise HTTPException(
                status_code=400,
                detail="Trạng thái phải là ACTIVE hoặc INACTIVE",
            )
        user.status = normalized_status
    if user.email and db.query(User).filter(
        User.email == user.email,
        User.id != user.id,
    ).first():
        raise HTTPException(status_code=400, detail="Email đã được sử dụng")

    role = normalize_role(user.role)
    if role == "EMPLOYEE":
        if user.employee is None:
            db.add(
                Employee(
                    user_id=user.id,
                    employee_code=f"EMP-{uuid4().hex[:8].upper()}",
                    position="Nhân viên",
                    status=user.status,
                )
            )
        else:
            user.employee.status = user.status
    elif user.employee is not None:
        user.employee.status = "INACTIVE"

    if role == "CUSTOMER":
        if user.customer_profile is None:
            db.add(
                Customer(
                    user_id=user.id,
                    customer_code=f"CUST-{uuid4().hex[:8].upper()}",
                    full_name=user.full_name,
                    email=user.email,
                    phone=user.phone,
                )
            )
        else:
            user.customer_profile.full_name = user.full_name
            user.customer_profile.email = user.email
            user.customer_profile.phone = user.phone
    elif user.customer_profile is not None:
        user.customer_profile.full_name = user.full_name
        user.customer_profile.email = user.email
        user.customer_profile.phone = user.phone

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Email hoặc mã hồ sơ đã được sử dụng",
        )
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Không thể tự khóa tài khoản hiện tại")

    user.status = "INACTIVE"
    if user.employee is not None:
        user.employee.status = "INACTIVE"
    db.commit()
    return {"message": "Đã khóa tài khoản người dùng"}
