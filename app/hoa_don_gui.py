import os
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from run_downloader_core import run

EMAIL_FILE = "emails.txt"

class HoaDonApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Tải Hóa Đơn Gmail")
        self.root.geometry("600x500")

        self.email_list = []
        self.load_emails()

        # Giao diện
        self.frame = ttk.Frame(root, padding=10)
        self.frame.pack(fill="both", expand=True)

        ttk.Label(self.frame, text="📩 Email người gửi:").grid(row=0, column=0, sticky="w")
        self.email_entry = ttk.Entry(self.frame, width=40)
        self.email_entry.grid(row=0, column=1, sticky="w")
        ttk.Button(self.frame, text="➕ Thêm", command=self.add_email).grid(row=0, column=2, padx=5)

        self.email_listbox = tk.Listbox(self.frame, height=6)
        self.email_listbox.grid(row=1, column=0, columnspan=3, sticky="we", pady=5)

        ttk.Label(self.frame, text="⏱️ Từ ngày (YYYY/MM/DD):").grid(row=2, column=0, sticky="w")
        self.start_entry = ttk.Entry(self.frame)
        self.start_entry.grid(row=2, column=1, sticky="w")

        ttk.Label(self.frame, text="⏱️ Đến ngày (YYYY/MM/DD):").grid(row=3, column=0, sticky="w")
        self.end_entry = ttk.Entry(self.frame)
        self.end_entry.grid(row=3, column=1, sticky="w")

        ttk.Button(self.frame, text="🚀 Tải hóa đơn", command=self.download).grid(row=4, column=1, pady=10)

        ttk.Label(self.frame, text="📄 Log xử lý:").grid(row=5, column=0, sticky="w", pady=(10, 0))
        self.log_text = tk.Text(self.frame, height=10)
        self.log_text.grid(row=6, column=0, columnspan=3, sticky="nsew")
        self.frame.rowconfigure(6, weight=1)

    def load_emails(self):
        if os.path.exists(EMAIL_FILE):
            with open(EMAIL_FILE, "r", encoding="utf-8") as f:
                self.email_list = [line.strip() for line in f if line.strip()]
        else:
            self.email_list = []

    def save_emails(self):
        with open(EMAIL_FILE, "w", encoding="utf-8") as f:
            for email in self.email_list:
                f.write(email + "\n")

    def add_email(self):
        email = self.email_entry.get().strip()
        if email and email not in self.email_list:
            self.email_list.append(email)
            self.save_emails()
            self.update_listbox()
        self.email_entry.delete(0, tk.END)

    def update_listbox(self):
        self.email_listbox.delete(0, tk.END)
        for email in self.email_list:
            self.email_listbox.insert(tk.END, email)

    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update()

    def download(self):
        senders = self.email_list
        start_date = self.start_entry.get().strip()
        end_date = self.end_entry.get().strip()

        try:
            datetime.strptime(start_date, "%Y/%m/%d")
            datetime.strptime(end_date, "%Y/%m/%d")
        except:
            messagebox.showerror("Lỗi", "Vui lòng nhập đúng định dạng ngày YYYY/MM/DD.")
            return

        self.log("🔄 Đang tải hóa đơn...")
        try:
            run(senders, start_date, end_date, self.log)
            self.log("✅ Hoàn tất!")
        except Exception as e:
            self.log(f"❌ Lỗi: {e}")

        self.root.update()

if __name__ == "__main__":
    root = tk.Tk()
    app = HoaDonApp(root)
    app.update_listbox()
    root.mainloop()
