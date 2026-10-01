from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas.auth import TokenResponse
from ..security import verify_password, create_access_token


router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)


@router.post(
    "/login",
    response_model=TokenResponse
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    # Tìm tài khoản
    user = db.query(User).filter(
        User.username == form_data.username
    ).first()

    # Không tìm thấy tài khoản
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tài khoản hoặc mật khẩu",
            headers={
                "WWW-Authenticate": "Bearer"
            }
        )

    # Kiểm tra mật khẩu
    if not verify_password(
        form_data.password,
        user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tài khoản hoặc mật khẩu",
            headers={
                "WWW-Authenticate": "Bearer"
            }
        )

    # Tạo JWT
    access_token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role
    })

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }