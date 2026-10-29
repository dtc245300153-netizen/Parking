from app.database import SessionLocal, Base, engine
from app.models import User
from app.security import hash_password


# Tạo các bảng nếu chưa có
Base.metadata.create_all(bind=engine)


db = SessionLocal()

try:
    # Kiểm tra admin đã tồn tại chưa
    existing_admin = db.query(User).filter(
        User.username == "admin"
    ).first()

    if existing_admin:
        print("Tài khoản admin đã tồn tại.")

        # Đảm bảo role là admin
        existing_admin.role = "admin"

        # Đặt lại mật khẩu
        existing_admin.password_hash = hash_password("123456")

        db.commit()

        print("Đã cập nhật:")
        print("Username: admin")
        print("Password: 123456")
        print("Role: admin")

    else:
        admin = User(
            username="admin",
            password_hash=hash_password("123456"),
            full_name="Administrator",
            role="admin"
        )

        db.add(admin)
        db.commit()

        print("Đã tạo tài khoản admin.")
        print("Username: admin")
        print("Password: 123456")
        print("Role: admin")

finally:
    db.close()