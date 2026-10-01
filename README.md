# Parking AI

Hệ thống quản lý bãi đỗ xe gồm FastAPI, SQLAlchemy, SQLite và giao diện HTML/JavaScript responsive.

## Cấu trúc

- `backend/app`: API, model, security và service layer.
- `backend/templates`: giao diện đăng nhập và dashboard Parking AI.
- `backend/parking.db`: SQLite database dùng cho bản demo hiện tại.
- `backend/seed_data.py`: tạo dữ liệu mẫu idempotent.
- `backend/backup_database.py`, `backend/restore_database.py`: backup/restore SQLite.
- `docs`: kiến trúc, rubric và nhật ký sử dụng AI.
- `database/backend`: bản sao legacy, không dùng trong launch hiện tại.

## Cài đặt

```powershell
cd backend
python -m pip install -r requirements.txt
Copy-Item ..\.env.example .env
python create_admin.py
python seed_data.py
```

## Chạy

```powershell
cd backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Mở `http://localhost:8080/login`.

Tài khoản demo được tạo bởi `create_admin.py`:

- Username: `admin`
- Password: `123456`

Đổi mật khẩu trước khi triển khai thật.

## API chính

- `POST /api/auth/login`: đăng nhập OAuth2 form.
- `/api/areas`, `/api/slots`, `/api/vehicles`, `/api/tickets`, `/api/prices`: CRUD nghiệp vụ.
- `GET /api/dashboard/summary`: chỉ số vị trí, xe, vé, doanh thu và công suất.
- `GET /api/revenue`: doanh thu theo thời gian/loại xe/ngày.
- `POST /api/ai/assistant`: data assistant truy vấn số liệu thật; không phải model generative.
- `GET /api/ai/capabilities`: trạng thái các AI capability.
- `GET /docs`: Swagger UI.

## Backup

Dừng server trước khi restore database.

```powershell
cd backend
python backup_database.py backups\parking-$(Get-Date -Format yyyyMMdd-HHmmss).db
python restore_database.py backups\parking-backup.db
```

## Kiểm tra

```powershell
cd backend
python -m compileall -q app backup_database.py restore_database.py seed_data.py
```

Giao diện đã được kiểm tra bằng browser flow đăng nhập, chuyển menu, bộ lọc vị trí, mở chi tiết vị trí và Parking AI Assistant.

## Lưu ý triển khai

- Dùng `SECRET_KEY` riêng, HTTPS, CORS allowlist và database PostgreSQL khi triển khai production.
- Để kết nối model OpenAI-compatible thật, cấu hình `AI_BASE_URL`, `AI_API_KEY` và `AI_MODEL` trong `.env`. Backend sẽ đưa context database vào model qua `app/services/ai.py`.
- Khi ba biến AI chưa có, assistant dùng data assistant deterministic; không giả lập AI generative.
- QR image renderer, reservation, số điện thoại, tầng và loại vị trí chưa được giả lập; các boundary/interface đã được chuẩn bị trong code và docs.
