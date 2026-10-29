from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import hash_password
from ..schemas.auth import UserResponse


router = APIRouter(
    prefix="/api/users",
    tags=["Users"]
)


@router.post("/", response_model=UserResponse)
def create_user(
    username: str,
    password: str,
    full_name: str,
    role: str = "employee",
    db: Session = Depends(get_db)
):
    existing_user = db.query(User).filter(
        User.username == username
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Tên đăng nhập đã tồn tại"
        )

    if role not in ["admin", "employee"]:
        raise HTTPException(
            status_code=400,
            detail="Role phải là admin hoặc employee"
        )

    user = User(
        username=username,
        password_hash=hash_password(password),
        full_name=full_name,
        role=role
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user