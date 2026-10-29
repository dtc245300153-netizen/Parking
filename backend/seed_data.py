from datetime import datetime, timedelta

from app.database import Base, SessionLocal, engine
from app.models import (
    AIConversation,
    AILog,
    Customer,
    Employee,
    ParkingArea,
    ParkingSlot,
    ParkingTicket,
    Payment,
    Pricing,
    User,
    Vehicle,
)
from app.security import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()


def ensure_admin_and_employee():
    admin = db.query(User).filter(User.username == "admin").first()
    if not admin:
        admin = User(
            username="admin",
            password_hash=hash_password("123456"),
            full_name="Administrator",
            email="admin@parking.local",
            phone="0900000001",
            role="ADMIN",
            status="ACTIVE",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

    employee = db.query(Employee).filter(Employee.employee_code == "EMP-001").first()
    if not employee:
        employee = db.query(Employee).filter(Employee.user_id == admin.id).first()
    if not employee:
        employee = Employee(
            user_id=admin.id,
            employee_code="EMP-001",
            position="Quản lý bãi",
            status="ACTIVE",
        )
        db.add(employee)
        db.commit()
        db.refresh(employee)

    return admin, employee


def ensure_customers():
    customer_rows = [
        ("CUST-001", "Nguyễn Văn An", "0901111111", "an.nguyen@gmail.com", "Hà Nội"),
        ("CUST-002", "Trần Thị Bình", "0902222222", "binh.tran@gmail.com", "Đà Nẵng"),
        ("CUST-003", "Lê Văn Cường", "0903333333", "cuong.le@gmail.com", "TP.HCM"),
        ("CUST-004", "Phạm Thị Duyên", "0904444444", "duyen.pham@gmail.com", "Cần Thơ"),
        ("CUST-005", "Hoàng Minh Thiện", "0905555555", "thien.hoang@gmail.com", "Đà Lạt"),
        ("CUST-006", "Võ Thị Lan", "0906666666", "lan.vo@gmail.com", "Nha Trang"),
    ]

    objs = []
    for code, full_name, phone, email, address in customer_rows:
        customer = db.query(Customer).filter(Customer.customer_code == code).first()
        if not customer:
            customer = Customer(
                customer_code=code,
                full_name=full_name,
                phone=phone,
                email=email,
                address=address,
            )
            db.add(customer)
            db.commit()
            db.refresh(customer)
        objs.append(customer)
    return objs


def ensure_vehicles(customers):
    vehicle_rows = [
        (customers[0].id, "30A-12345", "CAR", "Toyota", "Trắng"),
        (customers[1].id, "29B-67890", "MOTORBIKE", "Honda", "Đen"),
        (customers[0].id, "51C-11111", "EV", "VinFast", "Xanh"),
        (customers[2].id, "77D-22222", "CAR", "Mazda", "Bạc"),
        (customers[3].id, "56E-33333", "MOTORBIKE", "Yamaha", "Đỏ"),
        (customers[4].id, "59F-44444", "CAR", "Kia", "Khách"),
        (customers[5].id, "88G-66666", "EV", "Tesla", "Trắng"),
        (customers[2].id, "12H-10101", "MOTORBIKE", "Suzuki", "Xám"),
        (customers[4].id, "92K-76543", "CAR", "Ford", "Đen"),
        (customers[5].id, "99L-88888", "MOTORBIKE", "SYM", "Xanh"),
    ]

    objs = []
    for customer_id, plate, vehicle_type, brand, color in vehicle_rows:
        vehicle = db.query(Vehicle).filter(Vehicle.license_plate == plate).first()
        if not vehicle:
            vehicle = Vehicle(
                customer_id=customer_id,
                license_plate=plate,
                vehicle_type=vehicle_type,
                brand=brand,
                color=color,
            )
            db.add(vehicle)
            db.commit()
            db.refresh(vehicle)
        objs.append(vehicle)
    return objs


def ensure_parking_areas():
    area_a = db.query(ParkingArea).filter(ParkingArea.area_code == "AREA-A").first()
    if not area_a:
        area_a = ParkingArea(
            area_code="AREA-A",
            area_name="Khu A - Gần cổng chính",
            vehicle_type="CAR",
            capacity=20,
            status="ACTIVE",
            description="Khu dành cho ô tô và xe điện gần cổng vào.",
        )
        db.add(area_a)
        db.commit()
        db.refresh(area_a)

    area_b = db.query(ParkingArea).filter(ParkingArea.area_code == "AREA-B").first()
    if not area_b:
        area_b = ParkingArea(
            area_code="AREA-B",
            area_name="Khu B - Xe máy",
            vehicle_type="MOTORBIKE",
            capacity=30,
            status="ACTIVE",
            description="Khu dành cho xe máy và các phương tiện nhẹ.",
        )
        db.add(area_b)
        db.commit()
        db.refresh(area_b)

    return area_a, area_b


def ensure_slots(area_a, area_b):
    for slot_idx in range(1, 21):
        slot_code = f"A{slot_idx:02d}"
        slot = db.query(ParkingSlot).filter(ParkingSlot.slot_code == slot_code).first()
        if not slot:
            db.add(
                ParkingSlot(
                    area_id=area_a.id,
                    slot_code=slot_code,
                    status="OCCUPIED" if slot_idx in {1, 3, 6, 9, 12, 15, 18} else "EMPTY",
                    floor=1,
                    row_number=1,
                    column_number=slot_idx,
                )
            )

    for slot_idx in range(1, 31):
        slot_code = f"B{slot_idx:02d}"
        slot = db.query(ParkingSlot).filter(ParkingSlot.slot_code == slot_code).first()
        if not slot:
            db.add(
                ParkingSlot(
                    area_id=area_b.id,
                    slot_code=slot_code,
                    status="OCCUPIED" if slot_idx in {2, 5, 8, 11, 16, 19, 23, 27} else "EMPTY",
                    floor=1,
                    row_number=2,
                    column_number=slot_idx,
                )
            )
    db.commit()


def ensure_pricing_rules():
    pricing_rules = [
        ("CAR", 0, 120, 30000),
        ("CAR", 121, 240, 45000),
        ("MOTORBIKE", 0, 120, 10000),
        ("MOTORBIKE", 121, 240, 15000),
        ("EV", 0, 120, 35000),
        ("EV", 121, 240, 50000),
    ]

    for vehicle_type, from_minute, to_minute, price in pricing_rules:
        existing = db.query(Pricing).filter(
            Pricing.vehicle_type == vehicle_type,
            Pricing.from_minute == from_minute,
            Pricing.to_minute == to_minute,
        ).first()
        if not existing:
            db.add(
                Pricing(
                    vehicle_type=vehicle_type,
                    from_minute=from_minute,
                    to_minute=to_minute,
                    price=price,
                    effective_from=datetime.utcnow() - timedelta(days=30),
                    effective_to=None,
                    status="ACTIVE",
                )
            )
    db.commit()


def ensure_tickets_and_payments(employee):
    now = datetime.utcnow()
    active_records = [
        ("TICKET-900", "30A-12345", "A01", now - timedelta(hours=2, minutes=30), None, 0, "PARKING"),
        ("TICKET-901", "29B-67890", "B02", now - timedelta(hours=1, minutes=15), None, 0, "PARKING"),
    ]

    for ticket_code, plate, slot_code, check_in, check_out, amount, status in active_records:
        ticket = db.query(ParkingTicket).filter(ParkingTicket.ticket_code == ticket_code).first()
        if not ticket:
            vehicle = db.query(Vehicle).filter(Vehicle.license_plate == plate).first()
            slot = db.query(ParkingSlot).filter(ParkingSlot.slot_code == slot_code).first()
            if vehicle and slot:
                ticket = ParkingTicket(
                    ticket_code=ticket_code,
                    vehicle_id=vehicle.id,
                    slot_id=slot.id,
                    employee_id=employee.id,
                    check_in=check_in,
                    check_out=check_out,
                    amount=amount,
                    status=status,
                    created_at=check_in,
                )
                db.add(ticket)
                db.commit()
                db.refresh(ticket)
                slot.status = "OCCUPIED"
                db.commit()

    closed_records = [
        ("TICKET-100", "30A-12345", "A09", now - timedelta(hours=6), now - timedelta(hours=4), 150000, "PAID", "CASH"),
        ("TICKET-101", "77D-22222", "A11", now - timedelta(days=1, hours=2), now - timedelta(days=1, hours=1), 140000, "PAID", "BANK_TRANSFER"),
        ("TICKET-102", "88G-66666", "B15", now - timedelta(hours=9), now - timedelta(hours=6), 220000, "PAID", "QR"),
    ]
    utc_day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    demo_vehicles = [
        ("30A-12345", "A02"),
        ("29B-67890", "B03"),
        ("77D-22222", "A04"),
    ]
    for days_ago in range(7):
        for trip_index, hour_utc in enumerate((1, 10, 10)):
            check_in = utc_day_start - timedelta(days=days_ago) + timedelta(hours=hour_utc)
            if days_ago == 0:
                check_in = min(check_in, now - timedelta(hours=1))
            plate, slot_code = demo_vehicles[trip_index]
            ticket_code = f"DEMO-{check_in:%Y%m%d}-{trip_index + 1}"
            closed_records.append(
                (
                    ticket_code,
                    plate,
                    slot_code,
                    check_in,
                    check_in + timedelta(minutes=35 + trip_index * 10),
                    30000 + trip_index * 10000,
                    "PAID",
                    "CASH",
                )
            )

    for ticket_code, plate, slot_code, check_in, check_out, amount, ticket_status, payment_method in closed_records:
        ticket = db.query(ParkingTicket).filter(ParkingTicket.ticket_code == ticket_code).first()
        if ticket:
            continue

        vehicle = db.query(Vehicle).filter(Vehicle.license_plate == plate).first()
        slot = db.query(ParkingSlot).filter(ParkingSlot.slot_code == slot_code).first()
        if not vehicle or not slot:
            continue

        ticket = ParkingTicket(
            ticket_code=ticket_code,
            vehicle_id=vehicle.id,
            slot_id=slot.id,
            employee_id=employee.id,
            check_in=check_in,
            check_out=check_out,
            amount=amount,
            status=ticket_status,
            created_at=check_in,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)

        if not db.query(Payment).filter(Payment.ticket_id == ticket.id).first():
            db.add(
                Payment(
                    ticket_id=ticket.id,
                    payment_method=payment_method,
                    amount=amount,
                    paid_at=check_out,
                    employee_id=employee.id,
                    status="PAID",
                )
            )
            db.commit()

        slot.status = "EMPTY"
        db.commit()


def ensure_ai_logs(admin):
    if not db.query(AIConversation).first():
        db.add(
            AIConversation(
                user_id=admin.id,
                question="Có còn chỗ trống ở khu A vào lúc 17h-19h không?",
                answer="Hiện khu A còn 7 chỗ trống, khu B còn 12 chỗ trống. Vùng 17h-19h thuộc khung lưu lượng cao điểm, nên ưu tiên khu B nếu muốn di chuyển nhanh.",
                created_at=datetime.utcnow() - timedelta(hours=2),
            )
        )

    if not db.query(AILog).first():
        db.add(
            AILog(
                user_id=admin.id,
                prompt="Phân tích lưu lượng và chỗ trống theo giờ cao điểm",
                input_data='{"time_range": "17h-19h", "areas": ["AREA-A", "AREA-B"]}',
                output_data='{"area_a": "7 empty", "area_b": "12 empty", "peak": "17h-19h"}',
                feedback="positive",
                created_at=datetime.utcnow() - timedelta(hours=2),
            )
        )

    db.commit()


try:
    admin, employee = ensure_admin_and_employee()
    customers = ensure_customers()
    ensure_vehicles(customers)
    area_a, area_b = ensure_parking_areas()
    ensure_slots(area_a, area_b)
    ensure_pricing_rules()
    ensure_tickets_and_payments(employee)
    ensure_ai_logs(admin)
finally:
    db.close()
