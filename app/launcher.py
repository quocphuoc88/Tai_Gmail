# -*- coding: utf-8 -*-
"""Launcher đóng gói (.exe) cho "Tải Hóa Đơn Gmail".

Mục tiêu: gói sẵn Python + toàn bộ THƯ VIỆN vào .exe, nhưng MÃ NGUỒN của app
(gui.py, core/, providers/, docs/...) để RỜI trong thư mục ./app cạnh .exe.
Launcher chỉ nạp và chạy mã nguồn rời đó. Nhờ vậy:
  - Khách không cần cài Python.
  - Tính năng "Kiểm tra cập nhật" (ghi đè các file .py) VẪN hoạt động: lần mở
    sau launcher chạy mã nguồn mới mà KHÔNG cần gửi lại .exe.

Cách build: xem app/TaiHoaDonGmail.spec.
"""
import os
import sys
import runpy


def _force_bundle():
    """KHÔNG bao giờ gọi hàm này.

    Chỉ để PyInstaller dò ra toàn bộ thư viện mà app cần và gói vào .exe
    (gui kéo theo core/, providers/, google, selenium, tkcalendar, requests...).
    Các module CỦA APP (gui/core/providers) sẽ bị loại khỏi gói trong .spec để
    luôn chạy từ bản rời (cập nhật được).
    """
    import gui  # noqa: F401


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)   # thư mục chứa .exe
    return os.path.dirname(os.path.abspath(__file__))


def main():
    base = _base_dir()
    src = os.path.join(base, "app")              # mã nguồn rời, cập nhật được
    if not os.path.isdir(src):
        # Chạy trực tiếp từ mã nguồn (dev): app chính là thư mục chứa file này.
        src = os.path.dirname(os.path.abspath(__file__))

    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        os.chdir(src)
    except OSError:
        pass

    gui_py = os.path.join(src, "gui.py")
    try:
        runpy.run_path(gui_py, run_name="__main__")
    except Exception:
        import traceback
        msg = traceback.format_exc()
        try:
            with open(os.path.join(base, "loi_khoi_dong.txt"), "w", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw()
            messagebox.showerror(
                "Lỗi khởi động",
                "Ứng dụng gặp lỗi khi khởi động.\n"
                "Chi tiết đã ghi vào file 'loi_khoi_dong.txt' cạnh ứng dụng.\n\n"
                + msg[-800:],
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
