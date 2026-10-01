# Bài kiểm tra thường xuyên 2: Đối chiếu Parking AI

| Tiêu chí | Trạng thái | Minh chứng |
|---|---|---|
| Cấu trúc dự án | Đạt có điều kiện | `backend/app`, `backend/templates`, `docs`, `.vscode`; `database/backend` được ghi nhận là legacy duplicate. |
| Đăng nhập và phân quyền | Đạt sau bổ sung | JWT/OAuth2, role `admin/manager/staff`, dependency bảo vệ route, `.env.example`. |
| CRUD nghiệp vụ | Đạt | Khu vực, vị trí, phương tiện, vé, bảng giá trong `backend/app/main.py` và routers. |
| Tìm kiếm/lọc/sắp xếp | Đạt | Lọc vị trí theo mã/trạng thái/khu vực, tìm phương tiện, API order theo id; ticket/price có thể mở rộng cùng helper. |
| Thống kê/báo cáo | Đạt | Dashboard động, doanh thu ngày/tuần/tháng, công suất, phân bố trạng thái. |
| Giao diện/UX | Đạt | Loading, empty, error, confirm delete, notification chat, responsive CSS, modal chi tiết vị trí. |
| CSDL | Đạt | SQLAlchemy + SQLite, seed idempotent, 50 vị trí demo, backup/restore. |
| Xử lý lỗi | Đạt | Validation, HTTP status, API error parser, auth redirect, AI unsupported status. |
| Minh chứng AI | Đạt | `docs/ai-development-log.md` ghi prompt, phản hồi, phần kiểm tra/chỉnh sửa. |
| Mã nguồn/tài liệu chạy | Đạt sau bổ sung | `README.md`, `.env.example`, `docs/architecture.md`; Git repository chưa được khởi tạo trong workspace hiện tại. |

## Điểm cần nêu khi demo

- Tài khoản demo: `admin` / `123456`, chỉ dùng cho demo local.
- Số liệu dashboard lấy từ database, không lấy từ số cố định trong template.
- Parking AI Assistant là data assistant deterministic; model generative chưa được cấu hình và không được trình bày như đã hoạt động.
- Số điện thoại, tầng, loại vị trí và reservation chưa có trong schema hiện tại nên không được bịa trên giao diện.
