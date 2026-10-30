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
- `/api/users`, `/api/employees`: quản lý tài khoản và hồ sơ nhân viên (admin).
- `/api/reservations`: khách hàng đặt chỗ trước cho xe của mình; hệ thống giữ vị trí tối đa 30 phút, tác vụ nền quét mỗi 30 giây để tự chuyển sang `EXPIRED` và giải phóng chỗ; khách hàng có thể hủy. Nhân viên check-in xe đặt trước tại đúng vị trí đã giữ, chuyển trạng thái sang `IN_PARKING`.
- `/api/audit-logs`, `/api/notifications`: nhật ký admin và thông báo theo tài khoản.
- `GET /api/dashboard/summary`: chỉ số vị trí, xe, vé, doanh thu và công suất.
- `GET /api/revenue`: doanh thu theo thời gian/loại xe/ngày.
- `GET /api/reports/revenue.xlsx`: tải báo cáo Excel gồm tổng quan doanh thu theo ngày và chi tiết vé đã thanh toán (chỉ Admin); có nút **Xuất Excel** tại màn hình Doanh thu.
- `POST /api/ai/assistant`: trợ lý truy vấn dữ liệu bãi xe; khách hàng có thể hỏi xe của mình đang gửi ở vị trí nào; Admin có thể hỏi danh sách nhân viên, doanh thu, lưu lượng theo ngày/tuần, giờ cao điểm và gợi ý bố trí nhân sự. Hỏi `Bạn có thể trả lời gì?` để xem gợi ý câu hỏi theo vai trò.
- `GET /api/ai/capabilities`: trạng thái các AI capability.
- `GET /docs`: Swagger UI.

## Phân quyền người dùng

Hệ thống dùng JWT và kiểm tra quyền ở API; menu trên giao diện chỉ là lớp hiển thị bổ sung.

| Vai trò | Quyền chính |
|---|---|
| Admin | Quản lý người dùng, nhân viên, bãi đỗ, bảng giá; xem thống kê và doanh thu; vận hành xe vào/ra. |
| Staff (`EMPLOYEE`) | Xem thông tin vận hành, check-in/check-out và tra cứu vé; không truy cập báo cáo doanh thu. |
| Customer | Chỉ xem phương tiện, vé và lịch sử thuộc tài khoản của mình; không truy cập dashboard hoặc dữ liệu doanh thu. |

Khi tạo tài khoản, API chấp nhận `STAFF` và chuẩn hóa thành role lưu trữ `EMPLOYEE`.

## Kịch bản demo AI

Sau khi đăng nhập và chạy `python seed_data.py`, mở Parking Assistant và thử:

- `Báo cáo lưu lượng xe tuần này theo ngày`
- `Khung giờ nào đông nhất tuần này?`
- `Gợi ý bố trí nhân sự tuần này`

Gợi ý nhân sự là phép ước tính minh bạch từ lượt xe vào giờ cao điểm, mặc định 10 lượt/nhân viên/giờ. Có thể chỉnh giả định bằng `AI_ARRIVALS_PER_EMPLOYEE_PER_HOUR` trong `backend/.env`; đây chưa phải dự báo AI hay công cụ lập lịch ca. Dữ liệu demo được seed idempotent để có lưu lượng trong 7 ngày gần nhất.

Trang mặc định **Tổng quan** gồm công suất, doanh thu, hoạt động gần đây, phân bổ khu vực và thông báo chưa đọc. Tài khoản admin có thêm **Nhân viên** và **Nhật ký hoạt động**; nhân viên thường không thấy các mục admin-only.

Hướng dẫn cấu hình provider thật, luồng demo, phạm vi test và checklist bàn giao nằm trong [docs/demo-and-handoff.md](docs/demo-and-handoff.md).

Trang mặc định sau đăng nhập là **Tổng quan**, gồm tình trạng sức chứa, doanh thu, biểu đồ xu hướng, phân bổ khu vực và lượt xe gần đây. Tài khoản admin có thêm mục **Nhân viên** để tạo tài khoản, cập nhật chức vụ và khóa/mở tài khoản.

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
python -m pytest -q tests
```

Giao diện đã được kiểm tra bằng browser flow đăng nhập, chuyển menu, bộ lọc vị trí, mở chi tiết vị trí và Parking AI Assistant.

## Lưu ý triển khai

- Dùng `SECRET_KEY` riêng, HTTPS, CORS allowlist và database PostgreSQL khi triển khai production.
- Parking AI supports local Ollama, Groq, and Gemini. Local Ollama avoids hosted API keys and provider quotas, but requires Ollama and a local model installed; response speed and quality depend on the computer. Its default configuration is `AI_PROVIDER=ollama`, `AI_BASE_URL=http://127.0.0.1:11434/v1`, and `AI_MODEL=qwen2.5:3b`.
- On older Windows GPU drivers, set the user environment variables `OLLAMA_VULKAN=0` and `GGML_VK_VISIBLE_DEVICES=-1`, then restart Ollama to use CPU inference.
- AI answers use model knowledge and do not search the live web; current information is not guaranteed. Parking facts and metrics continue to come from the project database. No provider can guarantee zero errors or answer literally everything.
- QR image renderer, reservation, số điện thoại, tầng và loại vị trí chưa được giả lập; các boundary/interface đã được chuẩn bị trong code và docs.
- Chưa có gói vé tháng hoặc quy tắc hiệu lực/thanh toán định kỳ; demo hiện tính phí theo thời lượng gửi và bảng giá hiện tại.
