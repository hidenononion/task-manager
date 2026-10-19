# Báo cáo bảo mật & nâng cấp

Ngày rà soát: 19/10/2026. Phạm vi: `app.py`, `templates/`, `static/js/`, `zalo_webhook.py`,
`zalo_scheduler.py`, `dns_server.py`, `deploy.sh`.

## 1. Lỗ hổng đã sửa

| # | Mức độ | Lỗ hổng | Cách sửa |
|---|--------|---------|----------|
| 1 | Nghiêm trọng | `SECRET_KEY` hard-code dự phòng → giả mạo session/cookie | Bắt buộc env `SECRET_KEY` ≥ 32 ký tự; nếu thiếu thì sinh file `instance/secret_key` (0600, đã gitignore) |
| 2 | Nghiêm trọng | Mật khẩu băm SHA-256 không salt | Chuyển sang scrypt của Werkzeug (`generate_password_hash`), tự động rehash khi user đăng nhập |
| 3 | Nghiêm trọng | Tài khoản `admin/admin123` mặc định | Tạo admin bằng `ADMIN_PASSWORD` hoặc mật khẩu ngẫu nhiên ghi vào `instance/admin_initial_password.txt`; cảnh báo trong log nếu vẫn dùng `admin123` |
| 4 | Cao | Upload ghi file theo `filename` gốc → path traversal (`../../`) | `safe_filename()` + `_uploads_path()` chặn mọi đường dẫn ra ngoài `uploads/`; tên lưu có tiền tố ngẫu nhiên |
| 5 | Cao | Upload giả mạo phần mở rộng (HTML đổi tên `.pdf`) | Kiểm tra magic bytes (`%PDF`, `PK..`, OLE header), giới hạn 20MB, đọc có giới hạn |
| 6 | Cao | Stored XSS ở trang chia sẻ công khai (`/share/<token>`) | Chuyển sang Jinja2 auto-escape (`templates/share.html`, `share_gone.html`) |
| 7 | Cao | XSS qua `innerHTML` + nội suy tiêu đề vào `onclick` | `escapeHtml()` escape cả `& < > " '`; bỏ username/title khỏi chuỗi JS inline, chỉ truyền id |
| 8 | Cao | Avatar/tên người dùng chèn thẳng vào HTML + `onerror` | Render avatar bằng DOM API (`renderAvatar()`), validate URL ở server |
| 9 | Cao | SSRF qua webhook/Slack/Teams (localhost, IP nội bộ, metadata, redirect) | `is_public_http_url()` chặn scheme lạ, host nội bộ, DNS resolve; tắt redirect khi gọi webhook |
| 10 | Cao | CSRF trên các API ghi dữ liệu | Cookie `SameSite=Lax` + kiểm tra `Origin`/`Sec-Fetch-Site` trong `before_request` |
| 11 | Cao | Brute-force đăng nhập/đăng ký | Rate limit 5 lần/5 phút (IP+username), 20 lần/5 phút/IP, 5 tài khoản/giờ/IP |
| 12 | Cao | Session fixation | `session.clear()` trước khi đăng nhập, cookie HttpOnly + Secure (khi HTTPS) |
| 13 | Trung bình | So sánh role bằng `role in 'bithu'` (so khớp chuỗi con) | Đổi sang `is_admin()` (`== 'bithu'`) ở mọi nơi |
| 14 | Trung bình | User thường có thể `assign_to`/`delete` qua API bulk | Các thao tác này chỉ dành cho admin |
| 15 | Trung bình | CSV/Formula injection khi export | `csv_safe()` thêm `'` trước `= + - @` (kể cả sau khoảng trắng đầu) |
| 16 | Trung bình | Link `javascript:`/`data:` trong attachment | `is_safe_link_url()` chỉ cho http(s) hoặc đường dẫn nội bộ |
| 17 | Trung bình | Thiếu security headers | CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS khi HTTPS |
| 18 | Trung bình | Lỗi/stack trace trả về client | Handler 500 trả JSON chung cho `/api/*`, log chi tiết ở server |
| 19 | Trung bình | Zalo webhook chấp nhận request khi chưa cấu hình `ZALO_APP_ID` | Default-deny chữ ký; GET trả `text/plain` để tránh reflected XSS |
| 20 | Trung bình | DNS server mở resolver trên `0.0.0.0:53` | Mặc định bind `127.0.0.1`; muốn chia sẻ LAN đặt `DNS_BIND=0.0.0.0` |
| 21 | Thấp | File cấu hình/token Zalo đọc được bởi user khác | `chmod 600` sau khi ghi |
| 22 | Thấp | Số tiền `NaN`/`Infinity` lọt vào quỹ | `math.isfinite()` cho mọi khoản tiền thủ công |
| 23 | Thấp | Race condition khi 2 người cùng nhận task / cùng đánh dấu done | `BEGIN IMMEDIATE` (SQLite) / `SELECT ... FOR UPDATE` (Postgres); trừ quỹ bằng UPDATE có điều kiện |

## 2. Nâng cấp hiệu năng & vận hành

- `GET /api/tasks` từ **4 query mỗi task** (N+1) xuống **4 query batch** cho toàn bộ danh sách
  (`serialize_tasks`), có chia lô 500 id để không vượt giới hạn tham số SQLite.
- `MAX_CONTENT_LENGTH` chặn request quá lớn trước khi đọc vào RAM.
- `ProxyFix` chỉ bật khi `TRUST_PROXY=1` (tránh giả mạo `X-Forwarded-For`).
- `deploy.sh` sinh `SECRET_KEY`, bật `SESSION_COOKIE_SECURE=1`, thêm `EnvironmentFile`,
  tạo `instance/`, `uploads/`, `database.db` và giao cho `www-data`.
- Thêm test hồi quy: `tests/test_security.py` (21 test).

## 3. Cấu hình cần biết

| Biến | Ý nghĩa |
|------|---------|
| `SECRET_KEY` | Bắt buộc khi deploy; ≥ 32 ký tự |
| `ADMIN_PASSWORD` | Mật khẩu admin cho lần khởi tạo DB đầu tiên (≥ 8 ký tự) |
| `SESSION_COOKIE_SECURE` | `1` khi chạy HTTPS (mặc định tự bật nếu `FLASK_ENV=production` hoặc có `DATABASE_URL`) |
| `TRUST_PROXY` | `1` khi chạy sau Nginx/reverse proxy |
| `TASKMGR_DB_PATH` | Đường dẫn SQLite thay thế (dùng cho test/backup) |
| `ALLOWED_*` | Không có; Origin được so khớp trực tiếp với `Host` |
| `DNS_BIND` | Mặc định `127.0.0.1`; đặt `0.0.0.0` nếu cần DNS cho LAN |

**Lưu ý migration:** mật khẩu cũ (SHA-256) vẫn đăng nhập được và tự động được nâng cấp.
`admin123` vẫn hoạt động trên DB cũ nhưng log sẽ cảnh báo — hãy đổi ngay. `SECRET_KEY`
mới làm mọi session cũ hết hiệu lực (người dùng chỉ cần đăng nhập lại).

## 4. Rủi ro còn lại (chưa xử lý)

- Cấu hình SQL ngoài (`ext_sql_config`) lưu mật khẩu dạng plaintext trong DB. Nếu cần,
  nên mã hoá bằng key từ env hoặc dùng secret manager.
- Rate limit lưu trong RAM từng worker; chạy nhiều worker/proxy cần Redis để chính xác.
- File đính kèm vẫn cho mọi user đã đăng nhập tải nếu biết URL (có tiền tố ngẫu nhiên).
  Nếu cần phân quyền theo task, bổ sung kiểm tra assignment trong `api_serve_file`.
- API `GET /api/tasks` trả toàn bộ task cho mọi đoàn viên (phục vụ bảng claim chung).
  Nếu có task nội bộ, cần thêm cột/role để lọc.
- `2FA` mới có cột DB, chưa có luồng bật/kiểm tra TOTP.
- Token Zalo vẫn lưu file JSON (đã chmod 600, đã gitignore); nên chuyển vào env/secret store.

## 5. Kiểm chứng

```bash
python -m unittest discover -s tests -v
```

Test bao phủ: hash/migration, rate limit, password policy, phân quyền admin, CSRF,
escaping trang share, upload traversal/giả mạo, tải file cần đăng nhập, SSRF webhook,
CSV injection, batch serialization, giới hạn số người nhận task.
