# -*- coding: utf-8 -*-
"""
bkav_downloader.py  (v2)
Tải hóa đơn gốc (PDF / XML) từ link tra cứu BKAV.
- Hỗ trợ link rút gọn  http://tracuu.ehoadon.vn/<MA_TRA_CUU>
  (tự follow redirect sang trang van.ehoadon.vn/TCHD?...)
- Cung cấp is_bkav_email() + download_bkav_invoice() để gọi từ gmail_sync.

Tích hợp:
    from providers.bkav import is_bkav_email, download_bkav_invoice
"""

import re
import logging
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# Mã tra cứu trong link rút gọn: tracuu.ehoadon.vn/NSTXA3LRDNC
TRACUU_LINK_PATTERN = r"tracuu\.ehoadon\.vn/([A-Za-z0-9]+)"


# =========================================================
# 1. NHẬN DIỆN EMAIL BKAV
# =========================================================
def is_bkav_email(subject: str, from_email: str, body_text: str) -> bool:
    text = " ".join(
        (x or "") for x in (subject, from_email, body_text)
    ).lower()

    keywords = [
        "tracuu.ehoadon.vn",
        "van.ehoadon.vn",
        "công nghệ bkav",
        "cong nghe bkav",
    ]
    return any(k in text for k in keywords)


# =========================================================
# 2. TÌM MÃ TRA CỨU TRONG BODY EMAIL
# =========================================================
def tim_ma_tra_cuu_bkav(body_text: str) -> str | None:
    """
    Ưu tiên lấy từ link  tracuu.ehoadon.vn/<MA>.
    Fallback: dòng 'Mã tra cứu là: XXXX' (trường hợp email plain text
    không còn link).
    """
    body_text = body_text or ""

    m = re.search(TRACUU_LINK_PATTERN, body_text, re.IGNORECASE)
    if m:
        return m.group(1)

    m = re.search(
        r"m[ãa]\s*tra\s*c[ứu]+u?\s*(?:l[àa])?\s*[:\-]?\s*([A-Z0-9]{8,})",
        body_text,
        re.IGNORECASE,
    )
    return m.group(1) if m else None


# =========================================================
# 3. HELPER: hidden field ASP.NET, link PDF, tên file
# =========================================================
def _lay_hidden_field(html: str, field_name: str) -> str:
    for attr in ("id", "name"):
        m = re.search(
            attr + r'="' + re.escape(field_name) + r'"[^>]*value="([^"]*)"',
            html,
        )
        if m:
            return m.group(1)
    return ""


def _lay_link_pdf(html: str) -> str | None:
    m = re.search(r"DownloadFile\?FilePath=([^&\"'<>\s]+)", html, re.IGNORECASE)
    if m:
        return unquote(m.group(1))
    m = re.search(r"[\"']([^\"']+\.pdf)[\"']", html, re.IGNORECASE)
    return m.group(1) if m else None


def _ten_file_tu_response(resp: requests.Response, mac_dinh: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.IGNORECASE)
    if m:
        return unquote(m.group(1).strip())
    return mac_dinh


def _base_url(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


# =========================================================
# 4. TẢI HÓA ĐƠN THEO LINK TRA CỨU
# =========================================================
def tai_hoa_don_bkav(
    link_tra_cuu: str,
    loai_file: str = "pdf",          # "pdf" hoặc "xml"
    thu_muc_luu: str | Path = "downloads",
    timeout: int = 30,
) -> Path:
    loai_file = loai_file.lower().strip()
    thu_muc_luu = Path(thu_muc_luu)
    thu_muc_luu.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    logger.info("GET %s", link_tra_cuu)
    resp = session.get(link_tra_cuu, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()

    # Link tracuu.ehoadon.vn/<MA> sẽ redirect sang trang chi tiết
    # -> dùng URL CUỐI CÙNG cho postback và link tải
    final_url = resp.url
    base = _base_url(final_url)
    html = resp.text

    if loai_file == "pdf":
        link_pdf = _lay_link_pdf(html)
        if not link_pdf:
            raise RuntimeError("Không tìm thấy link PDF trong trang tra cứu.")

        file_url = f"{base}/DownloadFile?FilePath={link_pdf}&BFType=1"
        ten_mac_dinh = link_pdf.rsplit("/", 1)[-1] or "hoadon_bkav.pdf"

        logger.info("Tải PDF: %s", file_url)
        r = session.get(file_url, timeout=timeout)
        r.raise_for_status()

        save_path = thu_muc_luu / _ten_file_tu_response(r, ten_mac_dinh)
        save_path.write_bytes(r.content)
        logger.info("Đã lưu: %s", save_path)
        return save_path

    elif loai_file == "xml":
        form_data = {
            "__EVENTTARGET": "LinkDownXML",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": _lay_hidden_field(html, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": _lay_hidden_field(html, "__VIEWSTATEGENERATOR"),
            "__VIEWSTATEENCRYPTED": "",
            "hdfIsClicked": "",
        }
        ev = _lay_hidden_field(html, "__EVENTVALIDATION")
        if ev:
            form_data["__EVENTVALIDATION"] = ev

        logger.info("POST (LinkDownXML) %s", final_url)
        r = session.post(
            final_url,
            data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": final_url,
            },
            timeout=timeout,
        )
        r.raise_for_status()

        if b"<html" in r.content[:500].lower():
            raise RuntimeError(
                "Server trả về HTML thay vì file XML "
                "(postback thất bại - kiểm tra hidden fields)."
            )

        save_path = thu_muc_luu / _ten_file_tu_response(r, "HoaDonBKAV.xml")
        save_path.write_bytes(r.content)
        logger.info("Đã lưu: %s", save_path)
        return save_path

    raise ValueError(f"loai_file không hợp lệ: {loai_file!r} (dùng 'pdf' hoặc 'xml')")


# =========================================================
# 5. HÀM GỌI TỪ GMAIL_SYNC (giống interface download_misa_invoice)
# =========================================================
def download_bkav_invoice(body_text: str, save_dir: str) -> bool:
    """
    Tìm mã tra cứu trong body email và tải cả PDF + XML.
    Trả về True nếu tải được ít nhất 1 file.
    """
    ma = tim_ma_tra_cuu_bkav(body_text)
    if not ma:
        logger.warning("Email BKAV nhưng không tìm thấy mã tra cứu.")
        return False

    link = f"http://tracuu.ehoadon.vn/{ma}"
    logger.info("BKAV - Mã tra cứu: %s -> %s", ma, link)

    ok = False
    for loai in ("pdf", "xml"):
        try:
            tai_hoa_don_bkav(link, loai, save_dir)
            ok = True
        except Exception as exc:  # noqa: BLE001
            logger.error("Lỗi tải %s (mã %s): %s", loai.upper(), ma, exc)
    return ok


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Test nhanh:
    # download_bkav_invoice("Mã tra cứu là: NSTXA3LRDNC http://tracuu.ehoadon.vn/NSTXA3LRDNC", "downloads")
