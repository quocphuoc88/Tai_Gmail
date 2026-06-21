"""Giao diện desktop hợp nhất cho bộ tải hóa đơn điện tử từ Gmail.

Thay cho việc mở từng file HDDT_*.py trong PyCharm. Cho phép:
- Chọn một hoặc nhiều khách (đọc từ clients.json).
- Tùy chọn ghi đè khoảng ngày bằng lịch.
- Chạy nền (không treo giao diện), log hiện trực tiếp.

Chạy:  ..\\.venv\\Scripts\\python.exe gui.py
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Đảm bảo import được core/ và providers/
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from core.config import load_clients  # noqa: E402

CLIENTS_FILE = os.path.join(APP_DIR, "clients.json")

# tkcalendar có sẵn trong venv; nếu thiếu thì fallback ô nhập tay.
try:
    from tkcalendar import DateEntry
    HAS_CALENDAR = True
except Exception:
    HAS_CALENDAR = False

_DONE = "__DONE__"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Tải Hóa Đơn Gmail — Hợp nhất")
        root.geometry("760x620")
        root.minsize(680, 560)

        self.log_q: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.client_vars: dict[str, tk.BooleanVar] = {}

        try:
            self.clients = load_clients(CLIENTS_FILE)
        except Exception as e:
            messagebox.showerror("Lỗi đọc clients.json", str(e))
            self.clients = {}

        self._build_ui()
        self.root.after(100, self._drain_log)

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        # --- Khách hàng ---
        box = ttk.LabelFrame(main, text="Khách hàng (chọn 1 hoặc nhiều)")
        box.pack(fill="x", **pad)

        grid = ttk.Frame(box)
        grid.pack(fill="x", padx=8, pady=6)
        for i, cid in enumerate(self.clients):
            var = tk.BooleanVar(value=False)
            self.client_vars[cid] = var
            cb = ttk.Checkbutton(grid, text=cid, variable=var)
            cb.grid(row=i // 4, column=i % 4, sticky="w", padx=6, pady=2)

        btns = ttk.Frame(box)
        btns.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Button(btns, text="Chọn tất cả", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(btns, text="Bỏ chọn", command=lambda: self._set_all(False)).pack(side="left", padx=6)

        # --- Tùy chọn ---
        opt = ttk.LabelFrame(main, text="Tùy chọn")
        opt.pack(fill="x", **pad)

        # Ghi đè ngày
        self.override_dates = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt, text="Ghi đè khoảng ngày", variable=self.override_dates,
            command=self._toggle_dates,
        ).grid(row=0, column=0, sticky="w", padx=8, pady=6)

        ttk.Label(opt, text="Từ ngày:").grid(row=0, column=1, sticky="e")
        ttk.Label(opt, text="Đến ngày:").grid(row=0, column=3, sticky="e")
        if HAS_CALENDAR:
            self.date_from = DateEntry(opt, date_pattern="yyyy-mm-dd", width=12, state="disabled")
            self.date_to = DateEntry(opt, date_pattern="yyyy-mm-dd", width=12, state="disabled")
        else:
            self.date_from = ttk.Entry(opt, width=14, state="disabled")
            self.date_to = ttk.Entry(opt, width=14, state="disabled")
        self.date_from.grid(row=0, column=2, sticky="w", padx=6)
        self.date_to.grid(row=0, column=4, sticky="w", padx=6)

        # Chế độ tải
        ttk.Label(opt, text="Chế độ tải:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.mode = tk.StringVar(value="config")
        ttk.Radiobutton(opt, text="Theo cấu hình", variable=self.mode, value="config").grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(opt, text="Tải tất cả", variable=self.mode, value="all").grid(row=1, column=2, sticky="w")
        ttk.Radiobutton(opt, text="Chỉ chưa đọc", variable=self.mode, value="unread").grid(row=1, column=3, sticky="w")

        # --- Nút hành động ---
        act = ttk.Frame(main)
        act.pack(fill="x", **pad)
        self.btn_dry = ttk.Button(act, text="Xem QUERY (thử)", command=self.on_dry_run)
        self.btn_dry.pack(side="left")
        self.btn_run = ttk.Button(act, text="🚀 Tải hóa đơn", command=self.on_run)
        self.btn_run.pack(side="left", padx=8)
        self.status = ttk.Label(act, text="Sẵn sàng.", foreground="#0a7")
        self.status.pack(side="right")

        # --- Log ---
        logbox = ttk.LabelFrame(main, text="Nhật ký")
        logbox.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(logbox, height=14, wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        # Ép trạng thái mặc định (tránh lỗi tri-state 'alternate' của ttk.Checkbutton):
        # mặc định KHÔNG ghi đè ngày -> dùng ngày trong clients.json.
        self.override_dates.set(False)
        self.mode.set("config")
        self._toggle_dates()

    def _set_all(self, value: bool):
        for var in self.client_vars.values():
            var.set(value)

    def _toggle_dates(self):
        state = "normal" if self.override_dates.get() else "disabled"
        try:
            self.date_from.configure(state=state)
            self.date_to.configure(state=state)
        except Exception:
            pass

    # -------------------------------------------------------------- logic
    def _selected_ids(self) -> list[str]:
        return [cid for cid, var in self.client_vars.items() if var.get()]

    def _date_value(self, widget) -> str:
        """Lấy chuỗi YYYY-MM-DD từ DateEntry hoặc Entry."""
        if HAS_CALENDAR:
            return widget.get_date().strftime("%Y-%m-%d")
        return widget.get().strip()

    def _apply_overrides(self, cfg):
        """Áp tùy chọn GUI lên một ClientConfig (đã nạp mới mỗi lần chạy)."""
        if self.override_dates.get():
            df = self._date_value(self.date_from)
            dt = self._date_value(self.date_to)
            if df:
                cfg.date_from = df
            if dt:
                cfg.date_to = dt
        if self.mode.get() == "all":
            cfg.download_all = True
        elif self.mode.get() == "unread":
            cfg.download_all = False
        return cfg

    def log_msg(self, msg: str):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)

    def on_dry_run(self):
        ids = self._selected_ids()
        if not ids:
            messagebox.showwarning("Chưa chọn khách", "Hãy chọn ít nhất một khách hàng.")
            return
        from core.engine import build_gmail_query
        clients = load_clients(CLIENTS_FILE)
        self.log_msg("===== XEM TRƯỚC (không gọi Gmail) =====")
        for cid in ids:
            cfg = self._apply_overrides(clients[cid])
            self.log_msg(f"[{cid}] QUERY: {build_gmail_query(cfg)}")
            self.log_msg(f"[{cid}] Lưu vào: {cfg.base_save_dir}")
        self.log_msg("")

    def on_run(self):
        if self.worker and self.worker.is_alive():
            return
        ids = self._selected_ids()
        if not ids:
            messagebox.showwarning("Chưa chọn khách", "Hãy chọn ít nhất một khách hàng.")
            return
        if not messagebox.askyesno(
            "Xác nhận",
            f"Bắt đầu tải hóa đơn cho {len(ids)} khách:\n{', '.join(ids)}\n\n"
            "Lần đầu mỗi khách sẽ mở trình duyệt để đăng nhập Google.",
        ):
            return

        self.btn_run.configure(state="disabled")
        self.btn_dry.configure(state="disabled")
        self.status.configure(text="Đang chạy...", foreground="#c60")
        self.log_msg(f"\n========== BẮT ĐẦU ({len(ids)} khách) ==========")

        self.worker = threading.Thread(target=self._work, args=(ids,), daemon=True)
        self.worker.start()

    def _work(self, ids: list[str]):
        """Chạy trong thread nền — KHÔNG đụng widget Tk trực tiếp, chỉ đẩy log qua queue."""
        def logger(msg):
            self.log_q.put(str(msg))

        try:
            from core.engine import run_with_retry
            clients = load_clients(CLIENTS_FILE)
            grand = 0
            for cid in ids:
                cfg = self._apply_overrides(clients[cid])
                try:
                    grand += run_with_retry(cfg, logger)
                except Exception as e:  # một khách lỗi không chặn các khách khác
                    logger(f"[{cid}] LỖI: {e}")
            logger(f"========== XONG. Tổng đã lưu: {grand} file ==========")
        except Exception as e:
            logger(f"LỖI NGHIÊM TRỌNG: {e}")
        finally:
            self.log_q.put(_DONE)

    def _drain_log(self):
        """Chạy trên main thread: lấy log từ queue, cập nhật giao diện an toàn."""
        try:
            while True:
                msg = self.log_q.get_nowait()
                if msg == _DONE:
                    self.btn_run.configure(state="normal")
                    self.btn_dry.configure(state="normal")
                    self.status.configure(text="Sẵn sàng.", foreground="#0a7")
                else:
                    self.log_msg(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
