from datetime import datetime, timedelta, timezone
import os

from dotenv import load_dotenv
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User


load_dotenv()

# =========================
# JWT CONFIG
# =========================

# Trong project thật nên đặt SECRET_KEY trong file .env
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "parking-ai-secret-key-change-later",
)

ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
)

ROLE_ALIASES = {
    "ADMIN": "ADMIN",
    "EMPLOYEE": "EMPLOYEE",
    "STAFF": "EMPLOYEE",
    "CUSTOMER": "CUSTOMER",
}


def canonical_role(role: str) -> str:
    normalized = (role or "").strip().upper()
    return ROLE_ALIASES.get(normalized, normalized)


# =========================
# PASSWORD
# =========================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


def hash_password(password: str) -> str:
    """Mã hóa mật khẩu."""
    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str
) -> bool:
    """Kiểm tra mật khẩu."""
    return pwd_context.verify(
        plain_password,
        hashed_password
    )


# =========================
# JWT
# =========================

def create_access_token(
    data: dict,
    expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES
) -> str:
    """Tạo JWT access token."""

    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes
    )

    to_encode.update({
        "exp": expire
    })

    return jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


def decode_access_token(token: str):
    """Giải mã JWT token."""

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        return payload

    except JWTError:
        return None


# =========================
# AUTHENTICATION
# =========================

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login"
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """
    Lấy người dùng hiện tại từ JWT token.
    """

    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )

    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không chứa thông tin người dùng",
        )

    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ID người dùng không hợp lệ",
        )

    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Người dùng không tồn tại",
        )

    if str(user.status or "").strip().upper() != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản đã bị khóa hoặc ngừng hoạt động",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if canonical_role(user.role) not in {"ADMIN", "EMPLOYEE", "CUSTOMER"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vai trò người dùng không hợp lệ",
        )

    return user


# =========================
# AUTHORIZATION
# =========================

def require_admin(
    current_user: User = Depends(get_current_user)
):
    """
    Chỉ cho phép tài khoản có role = admin.
    """

    if canonical_role(current_user.role) != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền quản trị"
        )

    return current_user


def require_employee_or_admin(
    current_user: User = Depends(get_current_user)
):
    """
    Cho phép cả admin và employee.
    """

    if canonical_role(current_user.role) not in {"ADMIN", "EMPLOYEE"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bạn không có quyền truy cập"
        )

    return current_user


def require_employee(
    current_user: User = Depends(get_current_user)
):
    if canonical_role(current_user.role) != "EMPLOYEE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ nhân viên mới được thực hiện nghiệp vụ này",
        )

    return current_user


def require_manager_or_admin(
    current_user: User = Depends(get_current_user),
):
    if canonical_role(current_user.role) not in {"ADMIN", "MANAGER"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ Admin hoặc Manager được thực hiện thao tác này",
        )

    return current_user


# =========================
# FLEXIBLE ROLE AUTHORIZATION
# =========================

def require_role(*allowed_roles: str):
    """
    Kiểm tra người dùng có một trong các role được cho phép hay không.

    Ví dụ:
        require_role("admin")
        require_role("admin", "employee")
    """

    def role_checker(
        current_user: User = Depends(get_current_user)
    ):
        if canonical_role(current_user.role) not in {
            canonical_role(role) for role in allowed_roles
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền thực hiện chức năng này"
            )

        return current_user

    return role_checker