# Tải Hóa Đơn Điện Tử từ Gmail

Công cụ tải hóa đơn điện tử (PDF/XML) từ Gmail cho nhiều công ty khách hàng,
tự phân loại vào thư mục theo từng khách, hỗ trợ nhiều nhà cung cấp HĐĐT
(BKAV, MISA, Viettel/WIN, Petrolimex, Softdream, link trực tiếp...).

## Cấu trúc dự án

```
Tai_Gmail/
├── app/                    # TOÀN BỘ MÃ NGUỒN (đã cứu ra khỏi .venv)
│   ├── providers/          # Bộ xử lý riêng cho từng nhà cung cấp HĐĐT
│   ├── main_downloader.py  # Lõi tải qua Gmail API
│   ├── run_downloader_core.py
│   ├── hoa_don_gui.py      # Giao diện Tkinter
│   ├── HDDT_*.py           # Các script theo từng khách (sẽ gộp ở Bước 2)
│   ├── Nhap_Misa.py        # Nhập dữ liệu vào MISA
│   ├── requirements.txt    # Thư viện cần cài
│   ├── credentials*.json   # (BÍ MẬT - không lên Git) OAuth client của Google
│   └── token*.json         # (BÍ MẬT - không lên Git) token đã cấp quyền
├── .venv/                  # Môi trường ảo (không lên Git) - bản code cũ còn ở đây làm dự phòng
└── .gitignore
```

## Cài đặt trên máy mới

```powershell
# 1. Tạo môi trường ảo
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Cài thư viện
pip install -r app\requirements.txt

# 3. Chép các file BÍ MẬT (không có trong Git) vào app\ :
#    credentials*.json, token*.json
#    -> lấy từ bản sao lưu an toàn (KHÔNG để lộ các file này)
```

## ⚠️ Lưu ý bảo mật

Các file `credentials*.json` và `token*.json` chứa khoá truy cập Gmail của bạn.
Chúng **đã được loại khỏi Git** (xem `.gitignore`). Hãy tự sao lưu chúng ở nơi
an toàn (ví dụ thư mục Dropbox riêng), **tuyệt đối không** đẩy lên kho mã công khai.

## Chạy tải hóa đơn (engine hợp nhất)

```powershell
cd app
..\.venv\Scripts\python.exe run_client.py --list          # xem các khách
..\.venv\Scripts\python.exe run_client.py GPHUC           # chạy 1 khách
..\.venv\Scripts\python.exe run_client.py GPHUC GPHD 157  # nhiều khách
..\.venv\Scripts\python.exe run_client.py --all           # tất cả
..\.venv\Scripts\python.exe run_client.py GPHUC --dry-run # chỉ in QUERY, không gọi Gmail
# Ghi đè ngày cho lần chạy này:
..\.venv\Scripts\python.exe run_client.py EMECC --from 2026-06-01 --to 2026-06-22
```

Mọi cấu hình từng khách nằm trong `app/clients.json`. **Thêm khách mới = thêm 1 khối JSON**, không cần copy file `.py`.

## Trạng thái tái cấu trúc

- [x] **Bước 1:** Cứu mã nguồn ra khỏi `.venv`, đưa vào Git.
- [x] **Bước 2:** Gộp các script `HDDT_*` thành 1 engine + `clients.json`.
  - Đã gộp: GPHUC, GPHD, 157, EMECC, TaiLoc.
  - Chưa gộp (giữ bản gốc): `HDDT_Sagitta.py` (chạy theo Excel).
  - File cũ chuyển vào `app/legacy/` làm dự phòng.
- [x] **Bước 3:** Dựng giao diện desktop hợp nhất (`app/gui.py`).

## Giao diện desktop

```powershell
cd app
..\.venv\Scripts\pythonw.exe gui.py
```

Chọn khách (nhiều), tùy chọn ghi đè ngày bằng lịch, chọn chế độ tải, bấm
**🚀 Tải hóa đơn**. Việc tải chạy nền (không treo giao diện), log hiện trực tiếp.
Nút **Xem QUERY (thử)** để kiểm tra trước mà không gọi Gmail.
