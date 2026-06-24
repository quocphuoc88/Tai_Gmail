# Nhật ký cập nhật — Tải Hóa Đơn Gmail

Repo: `quocphuoc88/Tai_Gmail` (nhánh `main`). Phiên bản ở `app/version.txt`.

## Cách đồng bộ / cập nhật
- **Bản clone khác của repo (session Claude khác):** `git pull origin main` để lấy hết thay đổi.
- **Máy khách dùng bản đóng gói (.exe):** bấm **🔄 Kiểm tra cập nhật** trong app
  để tự lên bản mới — áp dụng cho thay đổi ở mã nguồn `.py` (BKAV, thư mục lưu...).
  Thay đổi nằm TRONG `.exe` (vd thư viện selenium) thì phải **gửi lại file zip mới**.
- **Đóng gói bản gửi khách:** `\.venv\Scripts\python app\build_release.py`
  → `dist\TaiHoaDonGmail_v<ver>.zip`.

## Kiến trúc đóng gói (quan trọng)
`.exe` là **launcher** (chứa Python + thư viện); **mã nguồn app để RỜI** trong
`./app` cạnh exe → bản đóng gói **vẫn tự cập nhật code online** (không phải gửi
lại exe khi chỉ sửa `.py`). File liên quan: `app/launcher.py`,
`app/TaiHoaDonGmail.spec`, `app/build_release.py`. Dữ liệu người dùng
(`clients.json`, `credentials*.json`, `token*.json`) nằm trong `app/` cạnh exe.

---

## Lịch sử phiên bản

### v1.0.15
- Engine: bỏ gom theo công ty phát hành (provider DIRECT). Hóa đơn đổ thẳng vào
  thư mục đã chọn.

### v1.0.14
- Engine: bỏ tự tạo thư mục con theo email người gửi. Không cấu hình riêng thì
  đổ thẳng vào thư mục chọn; có `path_rules`/`folder_rules` thì lưu theo cấu hình.

### v1.0.13
- GUI: thêm nút **📁 Khôi phục dữ liệu bản cũ** (tab Cấu hình) — copy
  `clients.json` + `credentials*.json` + `token*.json` (+ `gui_state.json`) từ
  thư mục bản cũ sang bản mới → khỏi đăng nhập Google lại khi nhận file mới.

### v1.0.12
- **BKAV đổi domain:** `tracuu.ehoadon.vn` (link rút gọn) đã CHẾT (404 mọi mã).
  Nay vào thẳng `https://tchd.ehoadon.vn/TCHD?MTC=<mã>`.
- **Sửa đóng gói selenium:** thêm `collect_submodules('selenium')` trong spec —
  hết lỗi `No module named 'selenium.webdriver.chrome.webdriver'` (MISA/SmartSign).
  (Lỗi này nằm trong `.exe` → phải gửi lại zip mới.)

### v1.0.11
- GUI: cửa sổ con (Thêm khách, Bộ lọc) hiện **giữa cửa sổ chính**.
- Tiêu đề chuẩn: `Tải Hóa Đơn Gmail - By Trần Quốc Phước - 0907.012.012`
  (chỉ để ở thanh tiêu đề, gỡ bớt chỗ trùng cho đỡ rối).

### v1.0.10
- GUI: đổi tiêu đề cửa sổ; nút **"Xem QUERY (thử)"** → **"Xem cấu hình tải thử"**.

### v1.0.9
- Thêm logo ứng dụng (icon `.exe` + cửa sổ) → `app/icon.ico`.

### (build) Launcher + mã nguồn rời
- Chuyển sang kiến trúc launcher để bản đóng gói vẫn tự cập nhật online.

### v1.0.8
- Hướng dẫn: thêm phụ lục cách tạo file `credentials.json` từ Google Cloud.

### v1.0.7
- GUI: thêm nút **📖 Hướng dẫn sử dụng** + file `app/docs/huong_dan_su_dung.html`.

### v1.0.6
- Thêm provider **VNPT** (`vnpt-invoice.com.vn`) → `app/providers/vnpt.py`
  (token EmailInvoiceView → ajxPreview → checkCode → tải PDF + XML).

### v1.0.5
- Sửa provider **BKAV** theo trang mới `tchd.ehoadon.vn`: lấy GUID từ
  `ViewInvoice('...')` → trang `/Lookup` → tải PDF + XML.
