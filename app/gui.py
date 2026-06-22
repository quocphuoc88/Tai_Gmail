"""Giao diện desktop hợp nhất cho bộ tải hóa đơn điện tử từ Gmail.

Hai thẻ:
- "Tải hóa đơn": chọn khách (tên thân thiện), ghi đè ngày, chạy nền, log.
- "Cấu hình & Bộ lọc": sửa tên hiển thị, email tài khoản, thư mục mặc định,
  và bảng bộ lọc (email người gửi -> lưu vào thư mục). Lưu ngược về clients.json.

Chạy:  ..\\.venv\\Scripts\\pythonw.exe gui.py
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, scrolledtext, filedialog

# App luôn chạy từ MÃ NGUỒN RỜI (kể cả khi khởi động qua launcher .exe đã đóng
# gói) -> __file__ trỏ đúng thư mục app, dữ liệu & tài nguyên nằm cạnh đây.
# Nhờ vậy tính năng cập nhật online (ghi đè .py) vẫn hoạt động trong bản .exe.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
# token_*/credentials_* dùng đường dẫn tương đối -> đặt thư mục làm việc tại APP_DIR.
try:
    os.chdir(APP_DIR)
except OSError:
    pass
RESOURCE_DIR = APP_DIR  # docs/ nằm rời cạnh mã nguồn

from core.config import load_clients, save_clients, ClientConfig  # noqa: E402

CLIENTS_FILE = os.path.join(APP_DIR, "clients.json")
STATE_FILE = os.path.join(APP_DIR, "gui_state.json")  # nhớ cấu hình lần trước (riêng máy)

try:
    from tkcalendar import DateEntry
    HAS_CALENDAR = True
except Exception:
    HAS_CALENDAR = False

_DONE = "__DONE__"


class _QueueWriter:
    """Thay sys.stdout/stderr: mọi print() (kể cả từ providers) đổ vào Nhật ký.

    Quan trọng khi chạy bằng pythonw.exe (không có console): nếu không thay,
    sys.stdout là None và print() trong providers sẽ làm treo luồng tải.
    """

    def __init__(self, q: "queue.Queue[str]"):
        self.q = q

    def write(self, s):
        if s and s.strip():
            self.q.put(s.rstrip("\n"))

    def flush(self):
        pass

# Nhãn loại bộ lọc
T_PATH = "Thư mục riêng (đường dẫn đầy đủ)"
T_FOLDER = "Thư mục con (dưới thư mục mặc định)"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Tải Hóa Đơn Gmail - By Trần Quốc Phước - 0907.012.012")
        root.geometry("820x680")
        root.minsize(720, 600)
        try:
            root.iconbitmap(os.path.join(RESOURCE_DIR, "icon.ico"))
        except Exception:
            pass

        self.log_q: "queue.Queue[str]" = queue.Queue()
        # Đưa mọi print() (providers, traceback) vào Nhật ký, tránh treo dưới pythonw.
        sys.stdout = _QueueWriter(self.log_q)
        sys.stderr = _QueueWriter(self.log_q)
        self.worker: threading.Thread | None = None
        self.run_vars: dict[str, tk.BooleanVar] = {}
        self.run_checks: dict[str, ttk.Checkbutton] = {}

        self._reload_clients()

        self._build_toolbar(root)

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tab_run = ttk.Frame(self.nb)
        self.tab_cfg = ttk.Frame(self.nb)
        self.nb.add(self.tab_run, text="  Tải hóa đơn  ")
        self.nb.add(self.tab_cfg, text="  Cấu hình & Bộ lọc  ")

        self._build_run_tab()
        self._build_cfg_tab()
        self._load_state()  # khôi phục cấu hình lần trước (khách, ngày, chế độ)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_log)
        # Tự kiểm tra cập nhật khi mở (im lặng nếu lỗi mạng / chưa cấu hình)
        self.root.after(800, self._check_update_async)

    # ===================================================== CẬP NHẬT / TOOLBAR
    def _build_toolbar(self, root):
        from core.updater import local_version
        bar = ttk.Frame(root, padding=(10, 6, 10, 0))
        bar.pack(fill="x")
        ttk.Label(bar, text="Tải Hóa Đơn Gmail",
                  font=("Segoe UI", 11, "bold")).pack(side="left")
        self.ver_label = ttk.Label(bar, text=f"  v{local_version()}", foreground="#777")
        self.ver_label.pack(side="left")
        ttk.Button(bar, text="🔄 Kiểm tra cập nhật",
                   command=self._check_update_manual).pack(side="right")

    def _check_update_async(self, manual=False):
        """Kiểm tra cập nhật trong thread; đẩy kết quả qua hàng đợi."""
        def work():
            from core.updater import check_update, is_configured
            if not is_configured():
                if manual:
                    self.log_q.put(("__INFO__", "Cập nhật",
                                    "Chưa cấu hình nơi cập nhật.\nHãy điền repo GitHub vào "
                                    "app\\update_config.json (xem hướng dẫn)."))
                return
            has, rv, lv = check_update()
            if has:
                self.log_q.put(("__ASK_UPDATE__", rv, lv))
            elif manual:
                self.log_q.put(("__INFO__", "Cập nhật",
                                f"Bạn đang dùng bản mới nhất (v{lv})."))
        threading.Thread(target=work, daemon=True).start()

    def _check_update_manual(self):
        self._check_update_async(manual=True)

    def _do_update(self):
        self.nb.select(self.tab_run)
        self.log_msg("\n[Cập nhật] Bắt đầu tải bản mới...")

        def work():
            from core.updater import download_and_apply, pip_install_requirements
            def logger(m):
                self.log_q.put(str(m))
            ok, msg = download_and_apply(logger)
            if ok:
                pip_install_requirements(logger)
            self.log_q.put(("__INFO__", "Cập nhật", msg))
        threading.Thread(target=work, daemon=True).start()

    # ============================================================ DỮ LIỆU
    def _reload_clients(self):
        try:
            self.clients = load_clients(CLIENTS_FILE)
        except Exception as e:
            messagebox.showerror("Lỗi đọc clients.json", str(e))
            self.clients = {}

    def _label_for(self, cid: str) -> str:
        cfg = self.clients[cid]
        name = cfg.display_name or cid
        return f"{name}  ({cfg.email})" if cfg.email else name

    # ======================================================== THẺ TẢI HĐ
    def _build_run_tab(self):
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.tab_run, padding=8)
        main.pack(fill="both", expand=True)

        box = ttk.LabelFrame(main, text="Khách hàng (chọn 1 hoặc nhiều)")
        box.pack(fill="x", **pad)
        self.run_grid = ttk.Frame(box)
        self.run_grid.pack(fill="x", padx=8, pady=6)
        self._populate_run_checks()

        btns = ttk.Frame(box)
        btns.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Button(btns, text="Chọn tất cả", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(btns, text="Bỏ chọn", command=lambda: self._set_all(False)).pack(side="left", padx=6)

        opt = ttk.LabelFrame(main, text="Tùy chọn")
        opt.pack(fill="x", **pad)
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

        ttk.Label(opt, text="Chế độ tải:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.mode = tk.StringVar(value="config")
        ttk.Radiobutton(opt, text="Theo cấu hình", variable=self.mode, value="config").grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(opt, text="Tải tất cả", variable=self.mode, value="all").grid(row=1, column=2, sticky="w")
        ttk.Radiobutton(opt, text="Chỉ chưa đọc", variable=self.mode, value="unread").grid(row=1, column=3, sticky="w")

        act = ttk.Frame(main)
        act.pack(fill="x", **pad)
        self.btn_dry = ttk.Button(act, text="Xem cấu hình tải thử", command=self.on_dry_run)
        self.btn_dry.pack(side="left")
        self.btn_run = ttk.Button(act, text="🚀 Tải hóa đơn", command=self.on_run)
        self.btn_run.pack(side="left", padx=8)
        ttk.Button(act, text="📖 Hướng dẫn sử dụng",
                   command=self._open_guide).pack(side="left")
        self.status = ttk.Label(act, text="Sẵn sàng.", foreground="#0a7")
        self.status.pack(side="right")

        logbox = ttk.LabelFrame(main, text="Nhật ký")
        logbox.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(logbox, height=12, wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        self.override_dates.set(False)
        self.mode.set("config")
        self._toggle_dates()

    def _populate_run_checks(self):
        for w in self.run_grid.winfo_children():
            w.destroy()
        self.run_vars.clear()
        self.run_checks.clear()
        for i, cid in enumerate(self.clients):
            var = tk.BooleanVar(value=False)
            self.run_vars[cid] = var
            cb = ttk.Checkbutton(self.run_grid, text=self._label_for(cid), variable=var)
            cb.grid(row=i // 3, column=i % 3, sticky="w", padx=6, pady=2)
            self.run_checks[cid] = cb

    def _set_all(self, value: bool):
        for var in self.run_vars.values():
            var.set(value)

    def _toggle_dates(self):
        state = "normal" if self.override_dates.get() else "disabled"
        try:
            self.date_from.configure(state=state)
            self.date_to.configure(state=state)
        except Exception:
            pass

    # ---- Nhớ cấu hình lần trước (gui_state.json) ----
    def _set_date(self, widget, val):
        if not val:
            return
        try:
            if HAS_CALENDAR:
                widget.set_date(datetime.strptime(val, "%Y-%m-%d").date())
            else:
                widget.delete(0, tk.END)
                widget.insert(0, val)
        except Exception:
            pass

    def _save_state(self):
        try:
            df = dt = ""
            try:
                df, dt = self._date_value(self.date_from), self._date_value(self.date_to)
            except Exception:
                pass
            state = {
                "clients": self._selected_ids(),
                "override_dates": bool(self.override_dates.get()),
                "date_from": df,
                "date_to": dt,
                "mode": self.mode.get(),
            }
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_state(self):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            return
        for cid in st.get("clients", []):
            if cid in self.run_vars:
                self.run_vars[cid].set(True)
        if st.get("mode") in ("config", "all", "unread"):
            self.mode.set(st["mode"])
        od = bool(st.get("override_dates"))
        self.override_dates.set(od)
        self._toggle_dates()
        if od:
            self._set_date(self.date_from, st.get("date_from", ""))
            self._set_date(self.date_to, st.get("date_to", ""))

    def _on_close(self):
        self._save_state()
        self.root.destroy()

    def _selected_ids(self) -> list[str]:
        return [cid for cid, var in self.run_vars.items() if var.get()]

    def _date_value(self, widget) -> str:
        if HAS_CALENDAR:
            return widget.get_date().strftime("%Y-%m-%d")
        return widget.get().strip()

    def _apply_overrides(self, cfg):
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

    def _open_guide(self):
        """Mở file hướng dẫn sử dụng (HTML) bằng trình duyệt mặc định."""
        path = os.path.join(RESOURCE_DIR, "docs", "huong_dan_su_dung.html")
        if not os.path.isfile(path):
            messagebox.showwarning(
                "Không tìm thấy hướng dẫn",
                "Chưa có file hướng dẫn. Hãy bấm '🔄 Kiểm tra cập nhật' để tải bản mới nhất.",
            )
            return
        try:
            os.startfile(path)  # Windows: mở bằng app mặc định
        except Exception:
            import webbrowser
            webbrowser.open(f"file:///{path.replace(os.sep, '/')}")

    def on_dry_run(self):
        ids = self._selected_ids()
        if not ids:
            messagebox.showwarning("Chưa chọn khách", "Hãy chọn ít nhất một khách hàng.")
            return
        self._save_state()
        from core.engine import build_gmail_query
        clients = load_clients(CLIENTS_FILE)
        self.log_msg("===== XEM TRƯỚC (không gọi Gmail) =====")
        for cid in ids:
            cfg = self._apply_overrides(clients[cid])
            self.log_msg(f"[{self._label_for(cid)}] QUERY: {build_gmail_query(cfg)}")
            self.log_msg(f"    Lưu mặc định: {cfg.base_save_dir}")
        self.log_msg("")

    def on_run(self):
        if self.worker and self.worker.is_alive():
            return
        ids = self._selected_ids()
        if not ids:
            messagebox.showwarning("Chưa chọn khách", "Hãy chọn ít nhất một khách hàng.")
            return
        self._save_state()
        self.btn_run.configure(state="disabled")
        self.btn_dry.configure(state="disabled")
        self.status.configure(text="Đang chạy...", foreground="#c60")
        self.log_msg(f"\n========== BẮT ĐẦU ({len(ids)} khách) ==========")
        self.worker = threading.Thread(target=self._work, args=(ids,), daemon=True)
        self.worker.start()

    def _work(self, ids: list[str]):
        def logger(msg):
            self.log_q.put(str(msg))

        def notify(kind, cfg):
            name = cfg.display_name or cfg.client_id
            if kind == "first":
                self.log_q.put((
                    "__POPUP__", "Đăng nhập lần đầu",
                    f"Tài khoản '{name}' cần ĐĂNG NHẬP Google lần đầu.\n"
                    f"Cửa sổ trình duyệt sẽ mở — hãy chọn đúng email rồi cấp quyền.",
                ))
            else:
                self.log_q.put((
                    "__POPUP__", "Cần đăng nhập lại",
                    f"Tài khoản '{name}' đã HẾT HẠN đăng nhập (token Gmail).\n"
                    f"Cửa sổ trình duyệt sẽ mở để ĐĂNG NHẬP LẠI.",
                ))

        try:
            from core.engine import run_with_retry
            clients = load_clients(CLIENTS_FILE)
            grand = 0
            for cid in ids:
                cfg = self._apply_overrides(clients[cid])
                try:
                    grand += run_with_retry(cfg, logger, notify)
                except Exception as e:
                    logger(f"[{cid}] LỖI: {e}")
            logger(f"========== XONG. Tổng đã lưu: {grand} file ==========")
        except Exception as e:
            logger(f"LỖI NGHIÊM TRỌNG: {e}")
        finally:
            self.log_q.put(_DONE)

    def _drain_log(self):
        try:
            while True:
                item = self.log_q.get_nowait()
                # Yêu cầu hiện popup (đăng nhập lần đầu / đăng nhập lại)
                if isinstance(item, tuple) and item and item[0] == "__POPUP__":
                    messagebox.showwarning(item[1], item[2])
                    continue
                if isinstance(item, tuple) and item and item[0] == "__INFO__":
                    messagebox.showinfo(item[1], item[2])
                    continue
                if isinstance(item, tuple) and item and item[0] == "__ASK_UPDATE__":
                    rv, lv = item[1], item[2]
                    if messagebox.askyesno(
                        "Có bản cập nhật",
                        f"Đã có bản mới v{rv} (bạn đang dùng v{lv}).\n\n"
                        "Cập nhật ngay? (Dữ liệu và cấu hình của bạn được giữ nguyên.)",
                    ):
                        self._do_update()
                    continue
                if item == _DONE:
                    self.btn_run.configure(state="normal")
                    self.btn_dry.configure(state="normal")
                    self.status.configure(text="Sẵn sàng.", foreground="#0a7")
                else:
                    self.log_msg(item)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)

    # ===================================================== THẺ CẤU HÌNH
    def _build_cfg_tab(self):
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.tab_cfg, padding=8)
        main.pack(fill="both", expand=True)

        top = ttk.Frame(main)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Khách:").pack(side="left")
        self.cfg_client = tk.StringVar()
        self.cfg_combo = ttk.Combobox(top, textvariable=self.cfg_client, state="readonly", width=26)
        self.cfg_combo.pack(side="left", padx=6)
        self.cfg_combo.bind("<<ComboboxSelected>>", lambda e: self._load_editor())
        ttk.Button(top, text="➕ Thêm khách (Gmail)", command=self._add_client).pack(side="left", padx=4)
        ttk.Button(top, text="🗑️ Xóa khách", command=self._delete_client).pack(side="left")

        info = ttk.LabelFrame(main, text="Thông tin khách")
        info.pack(fill="x", **pad)
        ttk.Label(info, text="Tên hiển thị:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        self.ed_name = ttk.Entry(info, width=30)
        self.ed_name.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(info, text="Email tài khoản Gmail:").grid(row=0, column=2, sticky="e", padx=6, pady=4)
        self.ed_email = ttk.Entry(info, width=30)
        self.ed_email.grid(row=0, column=3, sticky="w", padx=6, pady=4)

        ttk.Label(info, text="Thư mục mặc định:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        self.ed_root = ttk.Entry(info, width=66)
        self.ed_root.grid(row=1, column=1, columnspan=2, sticky="we", padx=6, pady=4)
        ttk.Button(info, text="Chọn...", command=self._browse_root).grid(row=1, column=3, sticky="w", padx=6)
        ttk.Label(
            info,
            text="(Nơi lưu cho email CHƯA có trong bộ lọc. Có thể dùng {date} = ngày hôm nay.)",
            foreground="#777",
        ).grid(row=2, column=1, columnspan=3, sticky="w", padx=6)

        flt = ttk.LabelFrame(main, text="Bộ lọc — email người gửi sẽ lưu vào thư mục riêng")
        flt.pack(fill="both", expand=True, **pad)

        rbtn = ttk.Frame(flt)
        rbtn.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(rbtn, text="➕ Thêm", command=self._add_rule).pack(side="left")
        ttk.Button(rbtn, text="✏️ Sửa", command=self._edit_rule).pack(side="left", padx=6)
        ttk.Button(rbtn, text="🗑️ Xóa", command=self._del_rule).pack(side="left")
        ttk.Label(rbtn, text="(bấm đúp một dòng để sửa nhanh)", foreground="#777").pack(side="left", padx=10)

        treewrap = ttk.Frame(flt)
        treewrap.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("email", "folder", "type")
        self.tree = ttk.Treeview(treewrap, columns=cols, show="headings", height=8)
        self.tree.heading("email", text="Email người gửi")
        self.tree.heading("folder", text="Lưu vào thư mục")
        self.tree.heading("type", text="Loại")
        self.tree.column("email", width=190)
        self.tree.column("folder", width=330)
        self.tree.column("type", width=150)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self._edit_rule())
        sb = ttk.Scrollbar(treewrap, orient="vertical", command=self.tree.yview)
        sb.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        bottom = ttk.Frame(main)
        bottom.pack(fill="x", **pad)
        ttk.Button(bottom, text="💾 Lưu cấu hình khách", command=self._save_editor).pack(side="left")
        self.cfg_status = ttk.Label(bottom, text="", foreground="#0a7")
        self.cfg_status.pack(side="left", padx=10)

        self._refresh_combo()

    def _refresh_combo(self):
        values = [self.clients[c].display_name or c for c in self.clients]
        self.cfg_combo["values"] = values
        self._name_to_id = {(self.clients[c].display_name or c): c for c in self.clients}
        if values and not self.cfg_client.get():
            self.cfg_combo.current(0)
            self._load_editor()

    def _current_cid(self) -> str | None:
        return self._name_to_id.get(self.cfg_client.get())

    def _load_editor(self):
        cid = self._current_cid()
        if not cid:
            return
        cfg = self.clients[cid]
        self.ed_name.delete(0, tk.END); self.ed_name.insert(0, cfg.display_name or cid)
        self.ed_email.delete(0, tk.END); self.ed_email.insert(0, cfg.email)
        self.ed_root.delete(0, tk.END); self.ed_root.insert(0, cfg.root_dir)
        # Nạp bộ lọc: path_rules (riêng) + folder_rules (con)
        self.rules: list[dict] = []
        for r in cfg.path_rules:
            self.rules.append({"kind": r.get("kind", "email"), "pattern": r.get("pattern", ""),
                               "dest": r.get("path", ""), "rtype": "path"})
        for r in cfg.folder_rules:
            self.rules.append({"kind": r.get("kind", "email"), "pattern": r.get("pattern", ""),
                               "dest": r.get("folder", ""), "rtype": "folder"})
        self._refresh_tree()
        self.cfg_status.configure(text="")

    def _refresh_tree(self):
        for it in self.tree.get_children():
            self.tree.delete(it)
        for r in self.rules:
            label = T_PATH if r["rtype"] == "path" else T_FOLDER
            self.tree.insert("", "end", values=(r["pattern"], r["dest"], label))

    def _browse_root(self):
        d = filedialog.askdirectory(title="Chọn thư mục mặc định")
        if d:
            self.ed_root.delete(0, tk.END)
            self.ed_root.insert(0, d.replace("/", "\\"))

    def _center_dialog(self, dlg):
        """Đưa cửa sổ con ra GIỮA cửa sổ chính (thay vì nhảy lên góc màn hình)."""
        try:
            dlg.update_idletasks()
            pw, ph = self.root.winfo_width(), self.root.winfo_height()
            px, py = self.root.winfo_rootx(), self.root.winfo_rooty()
            dw, dh = dlg.winfo_width(), dlg.winfo_height()
            x = px + max((pw - dw) // 2, 0)
            y = py + max((ph - dh) // 3, 0)
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ---- thêm/sửa/xóa bộ lọc ----
    def _rule_dialog(self, init: dict | None = None) -> dict | None:
        dlg = tk.Toplevel(self.root)
        dlg.title("Bộ lọc")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        result: dict = {}

        ttk.Label(dlg, text="Email người gửi:").grid(row=0, column=0, sticky="e", padx=8, pady=6)
        e_mail = ttk.Entry(dlg, width=40)
        e_mail.grid(row=0, column=1, columnspan=2, sticky="w", padx=8, pady=6)

        ttk.Label(dlg, text="Lưu vào:").grid(row=1, column=0, sticky="e", padx=8, pady=6)
        e_dest = ttk.Entry(dlg, width=40)
        e_dest.grid(row=1, column=1, sticky="w", padx=8, pady=6)
        rtype = tk.StringVar(value="path")

        def browse():
            d = filedialog.askdirectory(title="Chọn thư mục lưu")
            if d:
                e_dest.delete(0, tk.END)
                e_dest.insert(0, d.replace("/", "\\"))
                rtype.set("path")
        ttk.Button(dlg, text="Chọn...", command=browse).grid(row=1, column=2, padx=4)

        ttk.Label(dlg, text="Loại:").grid(row=2, column=0, sticky="e", padx=8, pady=6)
        ttk.Radiobutton(dlg, text=T_PATH, variable=rtype, value="path").grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(dlg, text=T_FOLDER, variable=rtype, value="folder").grid(row=3, column=1, columnspan=2, sticky="w")

        if init:
            e_mail.insert(0, init["pattern"])
            e_dest.insert(0, init["dest"])
            rtype.set(init["rtype"])

        def ok():
            patt = e_mail.get().strip()
            dest = e_dest.get().strip()
            if not patt or not dest:
                messagebox.showwarning("Thiếu thông tin", "Cần nhập cả email và thư mục.", parent=dlg)
                return
            result.update({
                "kind": init["kind"] if init else "email",
                "pattern": patt, "dest": dest, "rtype": rtype.get(),
            })
            dlg.destroy()

        bb = ttk.Frame(dlg)
        bb.grid(row=4, column=0, columnspan=3, pady=10)
        ttk.Button(bb, text="OK", command=ok).pack(side="left", padx=6)
        ttk.Button(bb, text="Hủy", command=dlg.destroy).pack(side="left", padx=6)
        self._center_dialog(dlg)
        e_mail.focus_set()
        self.root.wait_window(dlg)
        return result or None

    def _add_rule(self):
        r = self._rule_dialog()
        if r:
            self.rules.append(r)
            self._refresh_tree()

    def _selected_index(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.index(sel[0])

    def _edit_rule(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Chưa chọn", "Hãy chọn một dòng để sửa.")
            return
        r = self._rule_dialog(self.rules[idx])
        if r:
            self.rules[idx] = r
            self._refresh_tree()

    def _del_rule(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Chưa chọn", "Hãy chọn một dòng để xóa.")
            return
        if messagebox.askyesno("Xóa", f"Xóa bộ lọc:\n{self.rules[idx]['pattern']} ?"):
            del self.rules[idx]
            self._refresh_tree()

    def _save_editor(self):
        cid = self._current_cid()
        if not cid:
            return
        cfg = self.clients[cid]
        cfg.display_name = self.ed_name.get().strip() or cid
        cfg.email = self.ed_email.get().strip()
        cfg.root_dir = self.ed_root.get().strip()
        cfg.path_rules = [
            {"kind": r["kind"], "pattern": r["pattern"], "path": r["dest"]}
            for r in self.rules if r["rtype"] == "path"
        ]
        cfg.folder_rules = [
            {"kind": r["kind"], "pattern": r["pattern"], "folder": r["dest"]}
            for r in self.rules if r["rtype"] == "folder"
        ]
        try:
            save_clients(CLIENTS_FILE, self.clients)
        except Exception as e:
            messagebox.showerror("Lỗi lưu", str(e))
            return
        self._reload_clients()
        self._populate_run_checks()
        self._refresh_combo()
        # giữ nguyên khách đang chọn
        self.cfg_client.set(cfg.display_name)
        self._load_editor()
        self.cfg_status.configure(text="✅ Đã lưu vào clients.json")

    # ---- Thêm / xóa khách (tài khoản Gmail) ----
    def _add_client(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Thêm khách (tài khoản Gmail)")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        def field(label, r, width=46):
            ttk.Label(dlg, text=label).grid(row=r, column=0, sticky="e", padx=8, pady=5)
            e = ttk.Entry(dlg, width=width)
            e.grid(row=r, column=1, sticky="w", padx=8, pady=5)
            return e

        e_id = field("Mã khách (không dấu, vd GP2):", 0)
        e_name = field("Tên hiển thị:", 1)
        e_email = field("Email tài khoản:", 2)

        ttk.Label(dlg, text="File credentials (.json):").grid(row=3, column=0, sticky="e", padx=8, pady=5)
        e_cred = ttk.Entry(dlg, width=36)
        e_cred.grid(row=3, column=1, sticky="w", padx=8)

        def pick_cred():
            f = filedialog.askopenfilename(
                title="Chọn file credentials .json (tải từ Google Cloud)",
                filetypes=[("JSON", "*.json")], parent=dlg)
            if f:
                e_cred.delete(0, tk.END)
                e_cred.insert(0, f)
        ttk.Button(dlg, text="Chọn...", command=pick_cred).grid(row=3, column=2, padx=4)

        ttk.Label(dlg, text="Thư mục mặc định:").grid(row=4, column=0, sticky="e", padx=8, pady=5)
        e_root = ttk.Entry(dlg, width=36)
        e_root.grid(row=4, column=1, sticky="w", padx=8)

        def pick_root():
            d = filedialog.askdirectory(title="Chọn thư mục lưu mặc định", parent=dlg)
            if d:
                e_root.delete(0, tk.END)
                e_root.insert(0, d.replace("/", "\\"))
        ttk.Button(dlg, text="Chọn...", command=pick_root).grid(row=4, column=2, padx=4)

        ttk.Label(dlg, text="(Có thể dùng {date} trong đường dẫn = ngày hôm nay)",
                  foreground="#777").grid(row=5, column=1, sticky="w", padx=8)

        def submit():
            import re as _re
            cid = e_id.get().strip()
            cred = e_cred.get().strip()
            root = e_root.get().strip()
            if not _re.fullmatch(r"[A-Za-z0-9_]+", cid or ""):
                messagebox.showwarning("Sai mã", "Mã khách chỉ gồm chữ/số/gạch dưới (không dấu, không khoảng trắng).", parent=dlg)
                return
            if cid in self.clients:
                messagebox.showwarning("Trùng mã", f"Mã '{cid}' đã tồn tại.", parent=dlg)
                return
            if not (cred and os.path.isfile(cred)):
                messagebox.showwarning("Thiếu file", "Hãy chọn file credentials .json hợp lệ.", parent=dlg)
                return
            if not root:
                messagebox.showwarning("Thiếu thư mục", "Hãy chọn thư mục lưu mặc định.", parent=dlg)
                return
            data = (cid, e_name.get().strip(), e_email.get().strip(), cred, root)
            dlg.destroy()
            self._create_client(*data)

        bb = ttk.Frame(dlg)
        bb.grid(row=6, column=0, columnspan=3, pady=12)
        ttk.Button(bb, text="Đăng nhập Google & Lưu", command=submit).pack(side="left", padx=6)
        ttk.Button(bb, text="Hủy", command=dlg.destroy).pack(side="left", padx=6)
        self._center_dialog(dlg)
        e_id.focus_set()
        self.root.wait_window(dlg)

    def _create_client(self, cid, name, email, cred_src, root):
        dst_cred = f"credentials_{cid}.json"
        try:
            shutil.copyfile(cred_src, os.path.join(APP_DIR, dst_cred))
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không copy được file credentials: {e}")
            return
        cfg = ClientConfig(
            client_id=cid, credentials_file=dst_cred, token_file=f"token_{cid}.json",
            root_dir=root, display_name=name or cid, email=email,
        )
        self.nb.select(self.tab_run)
        self.log_msg(f"\n[Thêm khách] '{name or cid}' — mở trình duyệt đăng nhập Google...")

        def work():
            from core.engine import get_service
            def logger(m):
                self.log_q.put(str(m))
            try:
                get_service(cfg, logger)          # tạo token_<id>.json (mở trình duyệt)
                self.root.after(0, lambda: self._finish_add(cfg))
            except Exception as e:
                self.log_q.put(("__POPUP__", "Lỗi đăng nhập",
                                f"Không thêm được khách '{cid}':\n{e}"))
        threading.Thread(target=work, daemon=True).start()

    def _finish_add(self, cfg):
        self.clients[cfg.client_id] = cfg
        save_clients(CLIENTS_FILE, self.clients)
        self._reload_clients()
        self._populate_run_checks()
        self._refresh_combo()
        self.cfg_client.set(cfg.display_name or cfg.client_id)
        self._load_editor()
        messagebox.showinfo("Đã thêm khách",
                            f"Đã thêm '{cfg.display_name or cfg.client_id}' và lưu cấu hình.")

    def _delete_client(self):
        cid = self._current_cid()
        if not cid:
            return
        name = self.clients[cid].display_name or cid
        if not messagebox.askyesno(
            "Xóa khách",
            f"Xóa khách '{name}' khỏi danh sách?\n"
            "(Chỉ xóa khỏi cấu hình; KHÔNG xóa file credentials/token trên đĩa.)",
        ):
            return
        del self.clients[cid]
        save_clients(CLIENTS_FILE, self.clients)
        self._reload_clients()
        self._populate_run_checks()
        self.cfg_client.set("")
        self._refresh_combo()
        messagebox.showinfo("Đã xóa", f"Đã xóa '{name}'.")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
