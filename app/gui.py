"""Giao diện desktop hợp nhất cho bộ tải hóa đơn điện tử từ Gmail.

Hai thẻ:
- "Tải hóa đơn": chọn khách (tên thân thiện), ghi đè ngày, chạy nền, log.
- "Cấu hình & Bộ lọc": sửa tên hiển thị, email tài khoản, thư mục mặc định,
  và bảng bộ lọc (email người gửi -> lưu vào thư mục). Lưu ngược về clients.json.

Chạy:  ..\\.venv\\Scripts\\pythonw.exe gui.py
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from core.config import load_clients, save_clients  # noqa: E402

CLIENTS_FILE = os.path.join(APP_DIR, "clients.json")

try:
    from tkcalendar import DateEntry
    HAS_CALENDAR = True
except Exception:
    HAS_CALENDAR = False

_DONE = "__DONE__"

# Nhãn loại bộ lọc
T_PATH = "Thư mục riêng (đường dẫn đầy đủ)"
T_FOLDER = "Thư mục con (dưới thư mục mặc định)"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Tải Hóa Đơn Gmail — Hợp nhất")
        root.geometry("820x680")
        root.minsize(720, 600)

        self.log_q: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.run_vars: dict[str, tk.BooleanVar] = {}
        self.run_checks: dict[str, ttk.Checkbutton] = {}

        self._reload_clients()

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_run = ttk.Frame(self.nb)
        self.tab_cfg = ttk.Frame(self.nb)
        self.nb.add(self.tab_run, text="  Tải hóa đơn  ")
        self.nb.add(self.tab_cfg, text="  Cấu hình & Bộ lọc  ")

        self._build_run_tab()
        self._build_cfg_tab()
        self.root.after(100, self._drain_log)

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
        self.btn_dry = ttk.Button(act, text="Xem QUERY (thử)", command=self.on_dry_run)
        self.btn_dry.pack(side="left")
        self.btn_run = ttk.Button(act, text="🚀 Tải hóa đơn", command=self.on_run)
        self.btn_run.pack(side="left", padx=8)
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
        names = ", ".join(self.clients[c].display_name or c for c in ids)
        if not messagebox.askyesno(
            "Xác nhận",
            f"Bắt đầu tải hóa đơn cho {len(ids)} khách:\n{names}\n\n"
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

    # ===================================================== THẺ CẤU HÌNH
    def _build_cfg_tab(self):
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.tab_cfg, padding=8)
        main.pack(fill="both", expand=True)

        top = ttk.Frame(main)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Khách:").pack(side="left")
        self.cfg_client = tk.StringVar()
        self.cfg_combo = ttk.Combobox(top, textvariable=self.cfg_client, state="readonly", width=28)
        self.cfg_combo.pack(side="left", padx=6)
        self.cfg_combo.bind("<<ComboboxSelected>>", lambda e: self._load_editor())

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


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
