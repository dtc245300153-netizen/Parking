# Bài kiểm tra thường xuyên 2: Đối chiếu Parking AI

| Tiêu chí | Trạng thái | Minh chứng |
|---|---|---|
| Cấu trúc dự án | Đạt có điều kiện | `backend/app`, `backend/templates`, `docs`, `.vscode`; `database/backend` được ghi nhận là legacy duplicate. |
| Đăng nhập và phân quyền | Đạt một phần | JWT/OAuth2; runtime chấp nhận `admin`, `employee`/`staff`, `customer`. Chưa hỗ trợ role `manager`. |
| CRUD nghiệp vụ | Đạt một phần | Khu vực, vị trí, phương tiện, vé, bảng giá; admin có tạo tài khoản nhân viên, cập nhật chức vụ và khóa/mở tài khoản. Vé tháng chưa có quy tắc dữ liệu/giá nên chưa triển khai. |
| Tìm kiếm/lọc/sắp xếp | Đạt | Lọc vị trí theo mã/trạng thái/khu vực, tìm phương tiện, API order theo id; ticket/price có thể mở rộng cùng helper. |
| Thống kê/báo cáo | Đạt một phần | Trang Tổng quan có sức chứa, doanh thu, biểu đồ, khu vực và vé gần đây; dữ liệu refresh mỗi 10 giây. Assistant có lưu lượng ngày/tuần và giờ cao điểm theo giờ Việt Nam. Chưa có bộ lọc thời gian tùy ý. |
| Giao diện/UX | Đạt một phần | Loading, empty, error, confirm delete, Tổng quan, thông báo và responsive CSS; chưa có browser-test tự động. |
| CSDL | Đạt | SQLAlchemy + SQLite, seed idempotent, 50 vị trí demo, backup/restore. |
| Xử lý lỗi | Đạt | Validation, HTTP status, API error parser, auth redirect, AI unsupported status. |
| Minh chứng AI | Đạt một phần | Assistant truy vấn dữ liệu thật; provider có thể diễn giải gợi ý nhân sự từ ước tính backend. Kiểm thử provider dùng mock; cần cấu hình và xác nhận model thật trước khi tuyên bố đã tích hợp. Forecast công suất và nhận diện biển số chưa triển khai. |
| Kiểm thử | Đạt một phần | Có test traffic/timezone/peak, AI fallback/capabilities, login/phân quyền, quản lý nhân viên, check-in/out, cập nhật chỗ và phí 60/61 phút. Chưa có test browser tự động hoặc đánh giá chất lượng model thật. |
| Mã nguồn/tài liệu chạy | Đạt một phần | Có `README.md`, `.env.example`, tài liệu demo-bàn giao và Git repository riêng ở thư mục project; chưa có commit/remote hoặc hướng dẫn triển khai production. |

## Điểm cần nêu khi demo

- Tài khoản demo: `admin` / `123456`, chỉ dùng cho demo local.
- Số liệu dashboard lấy từ database, không lấy từ số cố định trong template.
- Demo assistant: `Báo cáo lưu lượng xe tuần này theo ngày`, `Khung giờ nào đông nhất tuần này?`, `Gợi ý bố trí nhân sự tuần này`.
- Gợi ý nhân sự là ước tính theo giả định mặc định 10 lượt/nhân viên/giờ. Provider chỉ diễn giải số backend đã tính; đây không phải dự báo hoặc lịch phân ca.
- Forecast công suất và nhận diện biển số chưa triển khai; không trình bày như đã hoạt động.
- Vé tháng/thanh toán định kỳ chưa triển khai; bảng giá hiện hành tính theo thời lượng gửi.
- Kịch bản cấu hình provider, lệnh chạy test, phạm vi test và checklist minh chứng nằm trong `docs/demo-and-handoff.md`.
- Số điện thoại, tầng, loại vị trí và reservation chưa có trong schema hiện tại nên không được bịa trên giao diện.
