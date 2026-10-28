from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Employee, User
from ..security import canonical_role, require_admin

router = APIRouter(prefix="/api/employees", tags=["Employees"])


@router.get("/")
def list_employees(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    del current_user
    return db.query(Employee).order_by(Employee.id).all()


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_employee(
    user_id: int,
    employee_code: str,
    position: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    if canonical_role(user.role) != "EMPLOYEE":
        raise HTTPException(
            status_code=400,
            detail="Chỉ người dùng có vai trò EMPLOYEE mới được tạo hồ sơ nhân viên",
        )
    if db.query(Employee).filter(Employee.employee_code == employee_code).first():
        raise HTTPException(status_code=400, detail="Mã nhân viên đã tồn tại")
    if db.query(Employee).filter(Employee.user_id == user_id).first():
        raise HTTPException(status_code=409, detail="Người dùng đã có hồ sơ nhân viên")
    employee_code = employee_code.strip()
    position = position.strip()
    if not employee_code or not position:
        raise HTTPException(
            status_code=400,
            detail="Mã và chức vụ nhân viên không được để trống",
        )

    employee = Employee(
        user_id=user_id,
        employee_code=employee_code,
        position=position,
        status=user.status,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee
