import tkinter as tk
from tkinter import filedialog
import xml.etree.ElementTree as ET
from openpyxl import Workbook

def chon_file():
    root = tk.Tk()
    root.withdraw()
    return filedialog.askopenfilename(filetypes=[("XML files", "*.xml")])

def doc_va_ghi_excel(filepath):
    tree = ET.parse(filepath)
    root = tree.getroot()

    wb = Workbook()
    ws = wb.active
    ws.title = "HoaDon"

    # Ghi tiêu đề
    ws.append([
        "THDon", "KHMSHDon", "KHHDon", "SHDon", "NLap",
        "NBan_Ten", "NBan_MST",
        "NMua_Ten", "NMua_MST",
        "TenHH", "SoLuong", "DonGia", "ThanhTien", "VAT"
    ])

    # Lấy thông tin chung
    ttchung = root.find(".//TTChung")
    nban = root.find(".//NBan")
    nmua = root.find(".//NMua")
    dshh = root.findall(".//HHDVu")

    if ttchung is not None and nban is not None and nmua is not None:
        thdon = ttchung.findtext("THDon", default="")
        khmshdon = ttchung.findtext("KHMSHDon", default="")
        khhdon = ttchung.findtext("KHHDon", default="")
        shdon = ttchung.findtext("SHDon", default="")
        nlap = ttchung.findtext("NLap", default="")

        nban_ten = nban.findtext("Ten", default="")
        nban_mst = nban.findtext("MST", default="")

        nmua_ten = nmua.findtext("Ten", default="")
        nmua_mst = nmua.findtext("MST", default="")

        # Mỗi hàng hóa là một dòng
        for hh in dshh:
            tenhh = hh.findtext("THHDVu", default="")
            soluong = hh.findtext("SLuong", default="")
            dongia = hh.findtext("DGia", default="")
            thanhtien = hh.findtext("ThTien", default="")
            vat = hh.findtext("TSuat", default="")

            ws.append([
                thdon, khmshdon, khhdon, shdon, nlap,
                nban_ten, nban_mst,
                nmua_ten, nmua_mst,
                tenhh, soluong, dongia, thanhtien, vat
            ])

    # Lưu file
    output_path = filepath.replace(".xml", "_hoadon.xlsx")
    wb.save(output_path)
    print(f"✅ Đã lưu file Excel tại: {output_path}")

# Chạy chương trình
filepath = chon_file()
if filepath:
    doc_va_ghi_excel(filepath)
else:
    print("❌ Bạn chưa chọn file.")
