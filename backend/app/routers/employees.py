from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Employee, User
from ..security import canonical_role, require_admin

router = APIRouter(prefix="/api/employees", tags=["Employees"])


class EmployeeUpdate(BaseModel):
    position: str = Field(min_length=1, max_length=50)


@router.get("/")
def list_employees(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    del current_user
    employees = db.query(Employee).order_by(Employee.id).all()
    return [
        {
            "id": employee.id,
            "user_id": employee.user_id,
            "employee_code": employee.employee_code,
            "position": employee.position,
            "status": employee.status,
            "username": employee.user.username,
            "full_name": employee.user.full_name,
            "email": employee.user.email or "",
            "phone": employee.user.phone or "",
        }
        for employee in employees
        if employee.user is not None
    ]


@router.put("/{employee_id}")
def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    del current_user
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if employee is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy nhân viên")

    position = payload.position.strip()
    if not position:
        raise HTTPException(status_code=400, detail="Chức vụ không được để trống")

    employee.position = position
    db.commit()
    db.refresh(employee)
    return {
        "id": employee.id,
        "employee_code": employee.employee_code,
        "position": employee.position,
        "status": employee.status,
    }


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
