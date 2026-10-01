from app.database import Base, engine, SessionLocal
from app.models import (
    Area,
    ParkingSlot,
    Vehicle,
    PriceRule,
    ParkingTicket
)

# Tạo bảng nếu chưa có
Base.metadata.create_all(bind=engine)

db = SessionLocal()

try:
    # =========================
    # 1. KHU VỰC
    # =========================

    area_a = db.query(Area).filter(
        Area.name == "Khu A"
    ).first()

    if not area_a:
        area_a = Area(
            name="Khu A",
            description="Khu vực đỗ xe chính"
        )
        db.add(area_a)
        db.commit()
        db.refresh(area_a)

    area_b = db.query(Area).filter(
        Area.name == "Khu B"
    ).first()

    if not area_b:
        area_b = Area(
            name="Khu B",
            description="Khu vực đỗ xe phụ"
        )
        db.add(area_b)
        db.commit()
        db.refresh(area_b)


    # =========================
    # 2. VỊ TRÍ ĐỖ XE
    # =========================

    slots = [
        *[(f"A{index:02d}", area_a.id) for index in range(1, 26)],
        *[(f"B{index:02d}", area_b.id) for index in range(1, 26)],
    ]

    for code, area_id in slots:

        exists = db.query(ParkingSlot).filter(
            ParkingSlot.slot_code == code
        ).first()

        if not exists:
            db.add(
                ParkingSlot(
                    slot_code=code,
                    area_id=area_id,
                    status="available"
                )
            )

    db.commit()


    # =========================
    # 3. PHƯƠNG TIỆN
    # =========================

    vehicles = [
        ("30A-12345", "Ô tô", "Nguyễn Văn An"),
        ("20B-67890", "Xe máy", "Trần Văn Bình"),
        ("29C-11111", "Ô tô", "Lê Văn Cường"),
        ("22B-22222", "Xe máy", "Phạm Văn Dũng"),
        ("30F-33333", "Ô tô", "Hoàng Văn Em"),
    ]

    for plate, vehicle_type, owner in vehicles:

        exists = db.query(Vehicle).filter(
            Vehicle.license_plate == plate
        ).first()

        if not exists:
            db.add(
                Vehicle(
                    license_plate=plate,
                    vehicle_type=vehicle_type,
                    owner_name=owner
                )
            )

    db.commit()


    # =========================
    # 4. BẢNG GIÁ
    # =========================

    prices = [
        ("Ô tô", 30000, 20000, 1500000),
        ("Xe máy", 10000, 5000, 300000),
    ]

    for vehicle_type, first, next_hour, monthly in prices:

        exists = db.query(PriceRule).filter(
            PriceRule.vehicle_type == vehicle_type
        ).first()

        if not exists:
            db.add(
                PriceRule(
                    vehicle_type=vehicle_type,
                    first_hour_price=first,
                    next_hour_price=next_hour,
                    monthly_price=monthly
                )
            )

    db.commit()


    print()
    print("====================================")
    print("   ĐÃ TẠO DỮ LIỆU MẪU THÀNH CÔNG")
    print("====================================")
    print()
    print(f"Khu vực : {db.query(Area).count()}")
    print(f"Vị trí   : {db.query(ParkingSlot).count()}")
    print(f"Phương tiện: {db.query(Vehicle).count()}")
    print(f"Bảng giá : {db.query(PriceRule).count()}")
    print()
    print("Bạn có thể F5 trang Parking AI.")
    print()


finally:
    db.close()