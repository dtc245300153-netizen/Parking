from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.main import calculate_pricing_fee
from app.models import (
    ActivityLog,
    Customer,
    Employee,
    Notification,
    ParkingArea,
    ParkingSlot,
    Pricing,
    User,
    Vehicle,
)
from app.security import hash_password


def _user(db_session, username, role):
    user = User(
        username=username,
        password_hash=hash_password("test-password-123"),
        full_name=username.title(),
        role=role,
        status="ACTIVE",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _login(client, username):
    response = client.post(
        "/api/auth/login",
        data={"username": username, "password": "test-password-123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_and_admin_only_revenue_report(client, db_session):
    admin = _user(db_session, "admin_test", "ADMIN")
    employee = _user(db_session, "employee_test", "EMPLOYEE")
    assert admin.id and employee.id

    invalid_login = client.post(
        "/api/auth/login",
        data={"username": "admin_test", "password": "wrong-password"},
    )
    assert invalid_login.status_code == 401

    admin_response = client.get(
        "/api/revenue",
        headers=_login(client, "admin_test"),
    )
    employee_response = client.get(
        "/api/revenue",
        headers=_login(client, "employee_test"),
    )

    assert admin_response.status_code == 200
    assert employee_response.status_code == 403


def test_ticket_entry_exit_updates_slot_and_charges_fee(client, db_session):
    employee_user = _user(db_session, "parking_staff", "EMPLOYEE")
    customer = Customer(customer_code="C-TEST", full_name="Test Customer")
    area = ParkingArea(
        area_code="AREA-TEST",
        area_name="Test Area",
        vehicle_type="CAR",
        capacity=1,
        status="ACTIVE",
    )
    db_session.add_all([customer, area])
    db_session.commit()
    slot = ParkingSlot(area_id=area.id, slot_code="TEST-01", status="EMPTY")
    vehicle = Vehicle(
        customer_id=customer.id,
        license_plate="TEST-123",
        vehicle_type="CAR",
    )
    db_session.add_all([slot, vehicle])
    db_session.add(
        Employee(
            user_id=employee_user.id,
            employee_code="EMP-TEST",
            position="Operator",
            status="ACTIVE",
        )
    )
    db_session.add(
        Pricing(
            vehicle_type="CAR",
            from_minute=0,
            to_minute=60,
            price=10000,
            effective_from=datetime.utcnow() - timedelta(days=1),
            status="ACTIVE",
        )
    )
    db_session.commit()
    headers = _login(client, "parking_staff")

    entry = client.post(
        "/api/tickets/entry",
        headers=headers,
        json={"vehicle_id": vehicle.id, "slot_id": slot.id},
    )

    assert entry.status_code == 200
    assert entry.json()["status"] == "PARKING"
    db_session.refresh(slot)
    assert slot.status == "OCCUPIED"

    exit_response = client.post(
        "/api/tickets/exit",
        headers=headers,
        json={"ticket_id": entry.json()["id"]},
    )

    assert exit_response.status_code == 200
    assert exit_response.json()["fee"] == 10000
    db_session.refresh(slot)
    assert slot.status == "EMPTY"


def test_pricing_selects_correct_duration_band_and_rejects_missing_rules(db_session):
    now = datetime.utcnow()
    db_session.add_all(
        [
            Pricing(
                vehicle_type="CAR",
                from_minute=0,
                to_minute=60,
                price=10000,
                effective_from=now - timedelta(days=1),
                status="ACTIVE",
            ),
            Pricing(
                vehicle_type="CAR",
                from_minute=61,
                to_minute=120,
                price=20000,
                effective_from=now - timedelta(days=1),
                status="ACTIVE",
            ),
        ]
    )
    db_session.commit()
    check_in = now - timedelta(minutes=60)

    assert calculate_pricing_fee(db_session, "CAR", check_in, now) == 10000
    assert calculate_pricing_fee(
        db_session,
        "CAR",
        now - timedelta(minutes=61),
        now,
    ) == 20000
    with pytest.raises(HTTPException) as error:
        calculate_pricing_fee(db_session, "TRUCK", check_in, now)
    assert error.value.status_code == 400


def test_employee_management_is_admin_only_and_returns_safe_profile_data(client, db_session):
    admin = _user(db_session, "staff_admin", "ADMIN")
    employee_user = _user(db_session, "staff_demo", "EMPLOYEE")
    employee = Employee(
        user_id=employee_user.id,
        employee_code="EMP-DEMO",
        position="Nhân viên",
        status="ACTIVE",
    )
    db_session.add(employee)
    db_session.commit()
    db_session.refresh(employee)
    admin_headers = _login(client, admin.username)

    employee_list = client.get("/api/employees/", headers=admin_headers)
    employee_forbidden = client.get(
        "/api/employees/",
        headers=_login(client, employee_user.username),
    )

    assert employee_list.status_code == 200
    assert employee_forbidden.status_code == 403
    row = next(item for item in employee_list.json() if item["id"] == employee.id)
    assert row["full_name"] == employee_user.full_name
    assert "password_hash" not in row

    position_response = client.put(
        f"/api/employees/{employee.id}",
        headers=admin_headers,
        json={"position": "Ca trưởng"},
    )
    lock_response = client.put(
        f"/api/users/{employee_user.id}",
        headers=admin_headers,
        json={"status": "INACTIVE"},
    )
    new_user_response = client.post(
        "/api/users",
        headers=admin_headers,
        json={
            "username": "new_staff",
            "password": "new-staff-password",
            "full_name": "New Staff",
            "role": "EMPLOYEE",
        },
    )

    assert position_response.status_code == 200
    assert position_response.json()["position"] == "Ca trưởng"
    assert lock_response.status_code == 200
    assert new_user_response.status_code == 201
    assert db_session.query(Employee).filter(
        Employee.user_id == new_user_response.json()["id"]
    ).first() is not None


def test_audit_logs_are_admin_only_and_notifications_can_be_marked_read(client, db_session):
    admin = _user(db_session, "audit_admin", "ADMIN")
    employee = _user(db_session, "audit_employee", "EMPLOYEE")
    log = ActivityLog(
        user_id=admin.id,
        action="ticket.entry",
        entity_type="ticket",
        details="Demo audit entry",
    )
    notification = Notification(
        user_id=None,
        level="success",
        title="Xe vào bãi",
        message="Demo notification",
        is_read=0,
    )
    db_session.add_all([log, notification])
    db_session.commit()
    admin_headers = _login(client, admin.username)
    employee_headers = _login(client, employee.username)

    admin_logs = client.get("/api/audit-logs", headers=admin_headers)
    employee_logs = client.get("/api/audit-logs", headers=employee_headers)
    unread = client.get(
        "/api/notifications?unread_only=true",
        headers=employee_headers,
    )
    marked_read = client.patch(
        f"/api/notifications/{notification.id}/read",
        headers=employee_headers,
    )

    assert admin_logs.status_code == 200
    assert admin_logs.json()[0]["action"] == "ticket.entry"
    assert employee_logs.status_code == 403
    assert any(item["id"] == notification.id for item in unread.json())
    assert marked_read.status_code == 200
    assert client.get(
        "/api/notifications?unread_only=true",
        headers=employee_headers,
    ).json() == []
