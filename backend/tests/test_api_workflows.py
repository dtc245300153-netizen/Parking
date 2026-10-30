from datetime import datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

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
    ParkingTicket,
    Pricing,
    Reservation,
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
    assert client.get(
        "/api/reports/revenue.xlsx",
        headers=_login(client, "employee_test"),
    ).status_code == 403


def test_admin_can_export_revenue_excel_with_paid_ticket_details(client, db_session):
    admin = _user(db_session, "excel_revenue_admin", "ADMIN")
    employee_user = _user(db_session, "excel_revenue_employee", "EMPLOYEE")
    customer = Customer(customer_code="EXCEL-CUST", full_name="Excel Customer")
    area = ParkingArea(
        area_code="EXCEL-AREA",
        area_name="Excel Area",
        vehicle_type="CAR",
        capacity=2,
    )
    employee = Employee(
        user_id=employee_user.id,
        employee_code="EXCEL-EMP",
        position="Nhân viên",
    )
    db_session.add_all([customer, area, employee])
    db_session.commit()
    vehicle = Vehicle(
        customer_id=customer.id,
        license_plate="EXCEL-123",
        vehicle_type="CAR",
    )
    paid_slot = ParkingSlot(
        area_id=area.id,
        slot_code="EXCEL-01",
        status="EMPTY",
    )
    parking_slot = ParkingSlot(
        area_id=area.id,
        slot_code="EXCEL-02",
        status="OCCUPIED",
    )
    db_session.add_all([vehicle, paid_slot, parking_slot])
    db_session.commit()
    db_session.add_all(
        [
            ParkingTicket(
                ticket_code="PAID-EXCEL-TICKET",
                vehicle_id=vehicle.id,
                slot_id=paid_slot.id,
                employee_id=employee.id,
                check_in=datetime(2026, 10, 29, 1, 0),
                check_out=datetime(2026, 10, 29, 2, 0),
                amount=35000,
                status="PAID",
            ),
            ParkingTicket(
                ticket_code="ACTIVE-EXCEL-TICKET",
                vehicle_id=vehicle.id,
                slot_id=parking_slot.id,
                employee_id=employee.id,
                check_in=datetime(2026, 10, 30, 1, 0),
                amount=0,
                status="PARKING",
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        "/api/reports/revenue.xlsx",
        headers=_login(client, admin.username),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment;" in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.content)) as workbook:
        assert "xl/workbook.xml" in workbook.namelist()
        assert len(workbook.namelist()) > 4
        workbook_content = b"".join(
            workbook.read(name)
            for name in workbook.namelist()
            if name.startswith("xl/worksheets/") or name == "xl/sharedStrings.xml"
        )
        assert b"PAID-EXCEL-TICKET" in workbook_content
        assert b"EXCEL-123" in workbook_content
        assert b"ACTIVE-EXCEL-TICKET" not in workbook_content


def test_change_password_requires_current_password_and_updates_hash(
    client,
    db_session,
):
    _user(db_session, "password_change_user", "CUSTOMER")
    headers = _login(client, "password_change_user")
    endpoint = "/api/auth/change-password"

    unauthenticated = client.post(
        endpoint,
        json={
            "old_password": "test-password-123",
            "new_password": "new-password-123",
            "confirm_password": "new-password-123",
        },
    )
    wrong_old_password = client.post(
        endpoint,
        headers=headers,
        json={
            "old_password": "incorrect-password",
            "new_password": "new-password-123",
            "confirm_password": "new-password-123",
        },
    )
    mismatched_confirmation = client.post(
        endpoint,
        headers=headers,
        json={
            "old_password": "test-password-123",
            "new_password": "new-password-123",
            "confirm_password": "different-password",
        },
    )

    assert unauthenticated.status_code == 401
    assert wrong_old_password.status_code == 400
    assert mismatched_confirmation.status_code == 400

    changed = client.post(
        endpoint,
        headers=headers,
        json={
            "old_password": "test-password-123",
            "new_password": "new-password-123",
            "confirm_password": "new-password-123",
        },
    )
    old_password_login = client.post(
        "/api/auth/login",
        data={
            "username": "password_change_user",
            "password": "test-password-123",
        },
    )
    new_password_login = client.post(
        "/api/auth/login",
        data={
            "username": "password_change_user",
            "password": "new-password-123",
        },
    )

    assert changed.status_code == 200
    assert changed.json()["message"] == "Đổi mật khẩu thành công"
    assert old_password_login.status_code == 401
    assert new_password_login.status_code == 200


def test_employee_can_register_vehicle_with_freely_typed_customer_name(
    client,
    db_session,
):
    _user(db_session, "vehicle_staff", "EMPLOYEE")

    response = client.post(
        "/api/vehicles/",
        headers=_login(client, "vehicle_staff"),
        data={
            "license_plate": "FREE-123",
            "vehicle_type": "car",
            "owner_name": "Khách hàng nhập tự do",
        },
    )

    assert response.status_code == 200
    assert response.json()["customer_name"] == "Khách hàng nhập tự do"
    assert (
        db_session.query(Customer)
        .filter(Customer.full_name == "Khách hàng nhập tự do")
        .count()
        == 1
    )


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
    user_list = client.get("/api/users", headers=admin_headers)
    employee_forbidden = client.get(
        "/api/employees/",
        headers=_login(client, employee_user.username),
    )

    assert employee_list.status_code == 200
    assert user_list.status_code == 200
    assert all("password_hash" not in user for user in user_list.json())
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
            "role": "STAFF",
        },
    )

    assert position_response.status_code == 200
    assert position_response.json()["position"] == "Ca trưởng"
    assert lock_response.status_code == 200
    assert new_user_response.status_code == 201
    assert new_user_response.json()["role"] == "EMPLOYEE"
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


def test_customer_only_sees_own_vehicles_and_ticket_history(client, db_session):
    customer_user = _user(db_session, "customer_owner", "CUSTOMER")
    other_user = _user(db_session, "customer_other", "CUSTOMER")
    employee_user = _user(db_session, "history_staff", "STAFF")
    own_customer = Customer(
        user_id=customer_user.id,
        customer_code="CUST-OWN",
        full_name="Own Customer",
    )
    other_customer = Customer(
        user_id=other_user.id,
        customer_code="CUST-OTHER",
        full_name="Other Customer",
    )
    area = ParkingArea(
        area_code="HISTORY-AREA",
        area_name="History Area",
        vehicle_type="CAR",
        capacity=2,
        status="ACTIVE",
    )
    employee = Employee(
        user_id=employee_user.id,
        employee_code="HISTORY-EMP",
        position="Nhân viên",
        status="ACTIVE",
    )
    db_session.add_all([own_customer, other_customer, area, employee])
    db_session.commit()

    own_vehicle = Vehicle(
        customer_id=own_customer.id,
        license_plate="OWN-123",
        vehicle_type="CAR",
    )
    other_vehicle = Vehicle(
        customer_id=other_customer.id,
        license_plate="OTHER-456",
        vehicle_type="CAR",
    )
    db_session.add_all([own_vehicle, other_vehicle])
    db_session.commit()
    own_slot = ParkingSlot(
        area_id=area.id,
        slot_code="HISTORY-01",
        status="EMPTY",
    )
    other_slot = ParkingSlot(
        area_id=area.id,
        slot_code="HISTORY-02",
        status="EMPTY",
    )
    db_session.add_all([own_slot, other_slot])
    db_session.commit()
    own_ticket = ParkingTicket(
        ticket_code="OWN-TICKET",
        vehicle_id=own_vehicle.id,
        slot_id=own_slot.id,
        employee_id=employee.id,
        check_in=datetime.utcnow() - timedelta(hours=2),
        status="PAID",
        amount=12000,
    )
    other_ticket = ParkingTicket(
        ticket_code="OTHER-TICKET",
        vehicle_id=other_vehicle.id,
        slot_id=other_slot.id,
        employee_id=employee.id,
        check_in=datetime.utcnow() - timedelta(hours=1),
        status="PAID",
        amount=50000,
    )
    db_session.add_all([own_ticket, other_ticket])
    db_session.commit()

    customer_headers = _login(client, customer_user.username)
    vehicles_response = client.get("/api/vehicles/", headers=customer_headers)
    tickets_response = client.get("/api/tickets/", headers=customer_headers)

    assert vehicles_response.status_code == 200
    assert [vehicle["license_plate"] for vehicle in vehicles_response.json()] == [
        "OWN-123"
    ]
    assert tickets_response.status_code == 200
    assert [ticket["ticket_code"] for ticket in tickets_response.json()] == [
        "OWN-TICKET"
    ]
    assert tickets_response.json()[0]["fee"] == 12000

    staff_headers = _login(client, employee_user.username)
    staff_ticket_list = client.get("/api/tickets/", headers=staff_headers)
    staff_ticket_detail = client.get(
        f"/api/tickets/{own_ticket.id}",
        headers=staff_headers,
    )
    assert staff_ticket_list.status_code == 200
    assert all("fee" not in ticket for ticket in staff_ticket_list.json())
    assert staff_ticket_detail.status_code == 200
    assert "amount" not in staff_ticket_detail.json()

    assert client.get("/api/dashboard/summary", headers=customer_headers).status_code == 403
    assert client.get("/api/dashboard", headers=customer_headers).status_code == 403
    assert client.get("/api/revenue", headers=customer_headers).status_code == 403


def test_staff_operates_parking_without_revenue_access(client, db_session):
    staff_user = _user(db_session, "role_staff", "STAFF")
    headers = _login(client, staff_user.username)

    assert client.get("/api/dashboard/summary", headers=headers).status_code == 200
    assert client.get("/api/revenue", headers=headers).status_code == 403
    assert client.get("/api/reports/revenue", headers=headers).status_code == 403

    summary = client.get("/api/dashboard/summary", headers=headers).json()
    assert "revenue" not in summary
    assert "total_revenue" not in summary


def test_customer_can_reserve_cancel_and_check_in_reserved_vehicle(client, db_session):
    customer_user = _user(db_session, "reservation_customer", "CUSTOMER")
    staff_user = _user(db_session, "reservation_staff", "EMPLOYEE")
    customer = Customer(
        user_id=customer_user.id,
        customer_code="RESERVATION-CUSTOMER",
        full_name="Reservation Customer",
    )
    area = ParkingArea(
        area_code="RESERVATION-AREA",
        area_name="Reservation Area",
        vehicle_type="CAR",
        capacity=2,
        status="ACTIVE",
    )
    employee = Employee(
        user_id=staff_user.id,
        employee_code="RESERVATION-EMP",
        position="Nhân viên",
        status="ACTIVE",
    )
    db_session.add_all([customer, area, employee])
    db_session.commit()
    booked_vehicle = Vehicle(
        customer_id=customer.id,
        license_plate="RESERVE-101",
        vehicle_type="CAR",
    )
    cancelled_vehicle = Vehicle(
        customer_id=customer.id,
        license_plate="RESERVE-102",
        vehicle_type="CAR",
    )
    other_customer = Customer(
        customer_code="RESERVATION-OTHER",
        full_name="Other Customer",
    )
    db_session.add(other_customer)
    db_session.commit()
    other_vehicle = Vehicle(
        customer_id=other_customer.id,
        license_plate="RESERVE-999",
        vehicle_type="CAR",
    )
    slots = [
        ParkingSlot(area_id=area.id, slot_code=f"RESERVE-0{number}", status="EMPTY")
        for number in range(1, 4)
    ]
    db_session.add_all([booked_vehicle, cancelled_vehicle, other_vehicle, *slots])
    db_session.commit()

    customer_headers = _login(client, customer_user.username)
    create_response = client.post(
        "/api/reservations",
        headers=customer_headers,
        json={"vehicle_id": booked_vehicle.id},
    )
    assert create_response.status_code == 201
    reservation = create_response.json()
    assert reservation["status"] == "RESERVED"
    assert reservation["vehicle_id"] == booked_vehicle.id
    assert reservation["slot_id"] is not None
    assert (datetime.fromisoformat(reservation["expire_time"]) -
            datetime.fromisoformat(reservation["reservation_time"])).total_seconds() == 1800
    assert db_session.get(ParkingSlot, reservation["slot_id"]).status == "RESERVED"

    duplicate = client.post(
        "/api/reservations",
        headers=customer_headers,
        json={"vehicle_id": booked_vehicle.id},
    )
    not_owned = client.post(
        "/api/reservations",
        headers=customer_headers,
        json={"vehicle_id": other_vehicle.id},
    )
    assert duplicate.status_code == 409
    assert not_owned.status_code == 404

    staff_headers = _login(client, staff_user.username)
    check_in = client.post(
        "/api/tickets/entry",
        headers=staff_headers,
        json={
            "vehicle_id": booked_vehicle.id,
            "slot_id": reservation["slot_id"],
        },
    )
    assert check_in.status_code == 200
    db_session.refresh(db_session.get(Reservation, reservation["id"]))
    assert db_session.get(Reservation, reservation["id"]).status == "IN_PARKING"
    checked_in_slot = db_session.get(ParkingSlot, reservation["slot_id"])
    db_session.refresh(checked_in_slot)
    assert checked_in_slot.status == "OCCUPIED"

    cancel_reservation = client.post(
        "/api/reservations",
        headers=customer_headers,
        json={"vehicle_id": cancelled_vehicle.id},
    )
    assert cancel_reservation.status_code == 201
    cancel_response = client.post(
        f"/api/reservations/{cancel_reservation.json()['id']}/cancel",
        headers=customer_headers,
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "CANCELLED"
    assert db_session.get(
        ParkingSlot, cancel_reservation.json()["slot_id"]
    ).status == "EMPTY"
    assert client.get(
        "/api/reservations/my",
        headers=customer_headers,
    ).status_code == 200


def test_reservation_expiration_marks_expired_and_releases_slot(
    client,
    db_session,
):
    from app.services.reservations import expire_reservations

    user = _user(db_session, "reservation_expiration", "CUSTOMER")
    customer = Customer(
        user_id=user.id,
        customer_code="RESERVATION-EXPIRATION",
        full_name="Reservation Expiration",
    )
    area = ParkingArea(
        area_code="RESERVATION-EXPIRATION-AREA",
        area_name="Reservation Expiration Area",
        vehicle_type="CAR",
        capacity=1,
        status="ACTIVE",
    )
    db_session.add_all([customer, area])
    db_session.commit()
    vehicle = Vehicle(
        customer_id=customer.id,
        license_plate="RESERVE-EXP",
        vehicle_type="CAR",
    )
    slot = ParkingSlot(
        area_id=area.id,
        slot_code="RESERVATION-EXP-SLOT",
        status="RESERVED",
    )
    db_session.add_all([vehicle, slot])
    db_session.commit()
    reservation = Reservation(
        user_id=user.id,
        vehicle_id=vehicle.id,
        slot_id=slot.id,
        status="RESERVED",
        reservation_time=datetime.utcnow() - timedelta(minutes=31),
        expire_time=datetime.utcnow() - timedelta(minutes=1),
    )
    db_session.add(reservation)
    db_session.commit()

    expired_count = expire_reservations(db_session)
    db_session.commit()
    db_session.refresh(reservation)
    db_session.refresh(slot)

    assert expired_count == 1
    assert reservation.status == "EXPIRED"
    assert slot.status == "EMPTY"


def test_customer_ai_context_and_revenue_are_role_scoped(client, db_session):
    from app.services.ai_service import build_ai_context

    customer_user = _user(db_session, "ai_customer", "CUSTOMER")
    other_user = _user(db_session, "ai_other", "CUSTOMER")
    employee_user = _user(db_session, "ai_staff", "EMPLOYEE")
    own_customer = Customer(
        user_id=customer_user.id,
        customer_code="AI-CUST-OWN",
        full_name="AI Own Customer",
    )
    other_customer = Customer(
        user_id=other_user.id,
        customer_code="AI-CUST-OTHER",
        full_name="AI Other Customer",
    )
    area = ParkingArea(
        area_code="AI-AREA",
        area_name="AI Area",
        vehicle_type="CAR",
        capacity=2,
        status="ACTIVE",
    )
    employee = Employee(
        user_id=employee_user.id,
        employee_code="AI-EMP",
        position="Nhân viên",
        status="ACTIVE",
    )
    db_session.add_all([own_customer, other_customer, area, employee])
    db_session.commit()
    own_vehicle = Vehicle(
        customer_id=own_customer.id,
        license_plate="AI-OWN-123",
        vehicle_type="CAR",
    )
    other_vehicle = Vehicle(
        customer_id=other_customer.id,
        license_plate="AI-OTHER-456",
        vehicle_type="CAR",
    )
    db_session.add_all([own_vehicle, other_vehicle])
    db_session.commit()
    own_slot = ParkingSlot(
        area_id=area.id,
        slot_code="AI-01",
        status="EMPTY",
    )
    other_slot = ParkingSlot(
        area_id=area.id,
        slot_code="AI-02",
        status="EMPTY",
    )
    db_session.add_all([own_slot, other_slot])
    db_session.commit()
    db_session.add_all(
        [
            ParkingTicket(
                ticket_code="AI-OWN-TICKET",
                vehicle_id=own_vehicle.id,
                slot_id=own_slot.id,
                employee_id=employee.id,
                check_in=datetime.utcnow(),
                amount=12000,
                status="PAID",
            ),
            ParkingTicket(
                ticket_code="AI-OTHER-TICKET",
                vehicle_id=other_vehicle.id,
                slot_id=other_slot.id,
                employee_id=employee.id,
                check_in=datetime.utcnow(),
                amount=50000,
                status="PAID",
            ),
        ]
    )
    db_session.commit()
    context = build_ai_context(db_session, customer_id=own_customer.id)

    assert [ticket["ticket_code"] for ticket in context["tickets"]] == [
        "AI-OWN-TICKET"
    ]
    assert context["tickets"][0]["license_plate"] == "AI-OWN-123"
    assert context["tickets"][0]["amount"] == 12000
    assert context["summary"]["vehicles"] == 1
    assert (
        client.post(
            "/api/ai/chat",
            headers=_login(client, customer_user.username),
            json={"question": "Doanh thu hôm nay là bao nhiêu?"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/ai/assistant",
            headers=_login(client, customer_user.username),
            json={"question": "Tổng doanh thu tháng này?"},
        ).status_code
        == 403
    )


def test_customer_ai_reports_only_their_vehicles_currently_parked(
    client,
    db_session,
    monkeypatch,
):
    from app.services import ai

    monkeypatch.setattr(ai, "get_configured_provider", lambda: None)
    customer_user = _user(db_session, "parked_ai_customer", "CUSTOMER")
    other_user = _user(db_session, "parked_ai_other", "CUSTOMER")
    staff_user = _user(db_session, "parked_ai_staff", "EMPLOYEE")
    customer = Customer(
        user_id=customer_user.id,
        customer_code="PARKED-AI-CUSTOMER",
        full_name="Parking AI Customer",
    )
    other_customer = Customer(
        user_id=other_user.id,
        customer_code="PARKED-AI-OTHER",
        full_name="Other Parking AI Customer",
    )
    area = ParkingArea(
        area_code="PARKED-AI-AREA",
        area_name="Parking AI Area",
        vehicle_type="CAR",
        capacity=2,
    )
    employee = Employee(
        user_id=staff_user.id,
        employee_code="PARKED-AI-EMPLOYEE",
        position="Nhân viên",
    )
    db_session.add_all([customer, other_customer, area, employee])
    db_session.commit()

    own_vehicle = Vehicle(
        customer_id=customer.id,
        license_plate="MY-CAR-123",
        vehicle_type="CAR",
    )
    other_vehicle = Vehicle(
        customer_id=other_customer.id,
        license_plate="OTHER-CAR-456",
        vehicle_type="CAR",
    )
    own_slot = ParkingSlot(
        area_id=area.id,
        slot_code="MY-SLOT-01",
        status="OCCUPIED",
    )
    other_slot = ParkingSlot(
        area_id=area.id,
        slot_code="OTHER-SLOT-02",
        status="OCCUPIED",
    )
    db_session.add_all([own_vehicle, other_vehicle, own_slot, other_slot])
    db_session.commit()
    db_session.add_all(
        [
            ParkingTicket(
                ticket_code="MY-CURRENT-TICKET",
                vehicle_id=own_vehicle.id,
                slot_id=own_slot.id,
                employee_id=employee.id,
                check_in=datetime.utcnow(),
                status="PARKING",
            ),
            ParkingTicket(
                ticket_code="OTHER-CURRENT-TICKET",
                vehicle_id=other_vehicle.id,
                slot_id=other_slot.id,
                employee_id=employee.id,
                check_in=datetime.utcnow(),
                status="PARKING",
            ),
        ]
    )
    db_session.commit()

    headers = _login(client, customer_user.username)
    for question in (
        "Xe tôi đang đỗ ở đâu?",
        "Xe của tôi đang gửi ở đâu?",
        "Xe mình hiện đang ở bãi nào?",
    ):
        response = client.post(
            "/api/ai/assistant",
            headers=headers,
            json={"question": question},
        )

        assert response.status_code == 200
        result = response.json()
        assert result["intent"] == "customer_parked_vehicles"
        assert "MY-CAR-123" in result["answer"]
        assert "MY-SLOT-01" in result["answer"]
        assert "OTHER-CAR-456" not in result["answer"]


def test_ai_lists_employees_for_admin_and_explains_supported_questions(
    client,
    db_session,
    monkeypatch,
):
    from app.services import ai

    monkeypatch.setattr(ai, "get_configured_provider", lambda: None)
    admin = _user(db_session, "ai_employee_admin", "ADMIN")
    customer = _user(db_session, "ai_employee_customer", "CUSTOMER")
    first_staff = _user(db_session, "ai_employee_first", "EMPLOYEE")
    second_staff = _user(db_session, "ai_employee_second", "EMPLOYEE")
    first_staff.full_name = "Nguyễn Văn An"
    second_staff.full_name = "Trần Thị Bình"
    db_session.add_all(
        [
            Employee(
                user_id=first_staff.id,
                employee_code="AI-EMP-001",
                position="Thu ngân",
                status="ACTIVE",
            ),
            Employee(
                user_id=second_staff.id,
                employee_code="AI-EMP-002",
                position="Bảo vệ",
                status="INACTIVE",
            ),
        ]
    )
    db_session.commit()

    directory = client.post(
        "/api/ai/assistant",
        headers=_login(client, admin.username),
        json={"question": "Tất cả nhân viên trong chương trình của tôi"},
    )
    assert directory.status_code == 200
    result = directory.json()
    assert result["intent"] == "employee_directory"
    assert "2 nhân viên" in result["answer"]
    assert "Nguyễn Văn An" in result["answer"]
    assert "ai_employee_first" not in result["answer"].lower()
    assert "Thu ngân" in result["answer"]
    assert {item["employee_code"] for item in result["data"]["employees"]} == {
        "AI-EMP-001",
        "AI-EMP-002",
    }

    help_response = client.post(
        "/api/ai/assistant",
        headers=_login(client, admin.username),
        json={"question": "Bạn có thể trả lời gì?"},
    )
    assert help_response.status_code == 200
    assert "Tất cả nhân viên" in help_response.json()["answer"]

    customer_headers = _login(client, customer.username)
    denied_directory = client.post(
        "/api/ai/assistant",
        headers=customer_headers,
        json={"question": "Tất cả nhân viên trong chương trình là ai?"},
    )
    customer_help = client.post(
        "/api/ai/assistant",
        headers=customer_headers,
        json={"question": "Bạn có thể trả lời gì?"},
    )
    assert denied_directory.status_code == 403
    assert customer_help.status_code == 200
    assert "nhân viên" not in customer_help.json()["answer"].lower()
    assert "doanh thu" not in customer_help.json()["answer"].lower()
