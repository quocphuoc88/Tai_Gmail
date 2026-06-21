"""Chạy tải hóa đơn cho một (hoặc nhiều) khách, đọc cấu hình từ clients.json.

Thay cho việc mở từng file HDDT_*.py riêng. Ví dụ:

    python run_client.py GPHUC                # chạy 1 khách
    python run_client.py GPHUC GPHD 157       # chạy nhiều khách
    python run_client.py --all                # chạy tất cả khách trong clients.json
    python run_client.py --list               # liệt kê các khách có sẵn
    python run_client.py GPHUC --dry-run      # chỉ in QUERY, KHÔNG gọi Gmail

Tùy chọn ghi đè ngày (áp cho mọi khách chạy lần này):
    python run_client.py GPHUC --from 2026-06-20 --to 2026-06-22
    python run_client.py GPHUC --download-all      # tải cả thư đã đọc
    python run_client.py GPHUC --unread-only       # chỉ thư chưa đọc
"""
from __future__ import annotations

import argparse
import os
import sys

# Đảm bảo thư mục app/ nằm trên sys.path để import core/, providers/
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from core.config import load_clients  # noqa: E402

CLIENTS_FILE = os.path.join(APP_DIR, "clients.json")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tải hóa đơn điện tử từ Gmail theo khách.")
    parser.add_argument("clients", nargs="*", help="Mã khách (vd GPHUC GPHD 157)")
    parser.add_argument("--all", action="store_true", help="Chạy tất cả khách")
    parser.add_argument("--list", action="store_true", help="Liệt kê khách có sẵn rồi thoát")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in QUERY, không gọi Gmail")
    parser.add_argument("--from", dest="date_from", help="Ghi đè ngày bắt đầu YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", help="Ghi đè ngày kết thúc YYYY-MM-DD")
    parser.add_argument("--download-all", action="store_true", help="Tải cả thư đã đọc")
    parser.add_argument("--unread-only", action="store_true", help="Chỉ thư chưa đọc")
    args = parser.parse_args(argv)

    all_clients = load_clients(CLIENTS_FILE)

    if args.list:
        print("Khách có trong clients.json:")
        for cid, cfg in all_clients.items():
            print(f"  - {cid:8} | creds={cfg.credentials_file:22} | root={cfg.root_dir}")
        return 0

    if args.all:
        selected = list(all_clients.keys())
    else:
        selected = args.clients

    if not selected:
        parser.error("Cần nêu mã khách, hoặc dùng --all / --list.")

    unknown = [c for c in selected if c not in all_clients]
    if unknown:
        parser.error(
            f"Không tìm thấy khách: {', '.join(unknown)}. "
            f"Có sẵn: {', '.join(all_clients)}"
        )

    grand_total = 0
    for cid in selected:
        cfg = all_clients[cid]
        # Áp ghi đè dòng lệnh
        if args.date_from:
            cfg.date_from = args.date_from
        if args.date_to:
            cfg.date_to = args.date_to
        if args.download_all:
            cfg.download_all = True
        if args.unread_only:
            cfg.download_all = False

        if args.dry_run:
            # Import muộn để --dry-run không cần thư viện Google
            from core.engine import build_gmail_query
            print(f"[{cid}] QUERY: {build_gmail_query(cfg)}")
            print(f"[{cid}] base_save_dir: {cfg.base_save_dir}")
            continue

        from core.engine import run_with_retry
        grand_total += run_with_retry(cfg)

    if not args.dry_run:
        print(f"\nTỔNG CỘNG đã lưu: {grand_total} file (qua {len(selected)} khách).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
