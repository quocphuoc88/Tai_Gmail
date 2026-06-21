from datetime import datetime
import os
from main_downloader import get_service, process_invoices

def run(senders, start_date, end_date, logger=None):
    sender_conditions = " OR ".join([f"from:{s}" for s in senders])
    query = f"({sender_conditions}) after:{start_date} before:{end_date}"

    today = datetime.today().strftime('%Y%m%d')
    save_dir = rf"D:\Tai HDDT\HOADONTN_{today}"
    log_file = os.path.join(save_dir, "log_hoadon.csv")

    service = get_service()
    if logger:
        logger(f"📥 Đang tìm email từ: {', '.join(senders)}")
        logger(f"📆 Khoảng thời gian: {start_date} - {end_date}")
        logger(f"💾 Thư mục lưu: {save_dir}")
    process_invoices(service, query=query, save_dir=save_dir, log_file=log_file, logger=logger)
