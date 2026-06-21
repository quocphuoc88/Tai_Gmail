"""Engine tải hóa đơn điện tử từ Gmail.

Rút từ HDDT_GPHUC.py (bản tiến hóa tốt nhất) và tham số hóa bằng ClientConfig,
để mọi khách dùng CHUNG một engine, chỉ khác cấu hình (clients.json).

Logic giữ nguyên hành vi bản gốc:
- Token hỏng/hết hạn -> tự xóa, đăng nhập lại.
- Ưu tiên 1: email có file đính kèm THẬT -> tải hết, bỏ qua provider.
- Ưu tiên 2: không đính kèm -> dò nhà cung cấp (MISA/BKAV/SOFTDREAM/PETROLIMEX/WIN/DIRECT).
- Khớp path_rules -> lưu thẳng đường dẫn riêng; nếu không -> root / (folder_rule | tên người gửi).
- download_all=False -> chỉ lấy thư chưa đọc; tải thành công mới đánh dấu đã đọc.
"""
from __future__ import annotations

import base64
import inspect
import re
import os
import unicodedata
from email.utils import parseaddr
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build

from core.config import ClientConfig, SCOPES

from providers.misa import download_misa_invoice
from providers.bkav import is_bkav_email, download_bkav_invoice
from providers.softdream import is_softdream_email, download_softdream_invoice
from providers.direct_link import is_direct_link_email, download_direct_invoice
from providers.petrolimex import is_petrolimex_email, download_petrolimex_invoice
from providers.win import is_win_email, download_win_invoice


# =========================================================
# CHECK EMAIL MISA
# =========================================================
def is_misa_email(subject, from_email, body_text):
    s = (subject or "").lower()
    f = (from_email or "").lower()
    b = (body_text or "").lower()
    keywords = ["meinvoice.vn", "misa"]
    text = f"{s} {f} {b}"
    return any(k in text for k in keywords)


# Danh sách nhà cung cấp hóa đơn. Thêm nhà mới = thêm 1 dòng.
# is_match(subject, from_email, body_text) sẽ tự lọc nên bật hết là an toàn.
PROVIDERS = [
    ("MISA", is_misa_email, download_misa_invoice),
    ("BKAV", is_bkav_email, download_bkav_invoice),
    ("SOFTDREAM", is_softdream_email, download_softdream_invoice),
    ("PETROLIMEX", is_petrolimex_email, download_petrolimex_invoice),
    ("WIN", is_win_email, download_win_invoice),
    ("DIRECT", is_direct_link_email, download_direct_invoice),
]


# =========================================================
# NORMALIZE / CHỌN THƯ MỤC
# =========================================================
def strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_sender_folder(from_email: str) -> str:
    local = from_email.split("@", 1)[0]
    local = strip_accents(local).lower()
    tokens = [t for t in re.split(r"[._+\s]+", local) if t]
    base = "-".join(tokens) if tokens else local
    base = re.sub(r"[^a-z0-9\-]", "", base)
    return base.upper() if base else "UNKNOWN"


def choose_folder_by_rules(from_email: str, folder_rules: List[Dict[str, str]]) -> Optional[str]:
    e = (from_email or "").strip().lower()
    domain = e.split("@", 1)[1] if "@" in e else ""
    for r in folder_rules:
        kind, patt, folder = r["kind"], r["pattern"], r["folder"]
        if kind == "email" and e == patt.lower():
            return folder
        if kind == "domain" and domain == patt.lower():
            return folder
        if kind == "regex" and re.fullmatch(patt, e, flags=re.IGNORECASE):
            return folder
    return None


def choose_brand_prefix(subject: str, cfg: ClientConfig) -> str:
    """Tiền tố tên file theo từ khóa trong tiêu đề (vd TaiLoc: ACECOOK/ÁCHÂU/HD).

    Trả về "" nếu khách không khai brand_rules.
    """
    if not cfg.brand_rules:
        return ""
    s = strip_accents(subject or "").upper()
    for r in cfg.brand_rules:
        kw = strip_accents(r.get("keyword", "")).upper()
        if kw and kw in s:
            return r.get("prefix", "")
    return cfg.brand_default


def choose_base_dir(from_email: str, cfg: ClientConfig) -> Optional[str]:
    """Đường dẫn lưu riêng nếu người gửi khớp path_rules; ngược lại None."""
    e = (from_email or "").strip().lower()
    domain = e.split("@", 1)[1] if "@" in e else ""
    for r in cfg.path_rules:
        kind, patt, path = r["kind"], r["pattern"], r["path"]
        if kind == "email" and e == patt.lower():
            return cfg.expand_tokens(path)
        if kind == "domain" and domain == patt.lower():
            return cfg.expand_tokens(path)
        if kind == "regex" and re.fullmatch(patt, e, flags=re.IGNORECASE):
            return cfg.expand_tokens(path)
    return None


# =========================================================
# TÊN FILE / ĐƯỜNG DẪN AN TOÀN
# =========================================================
def safe_filename(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    return name[:240]


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1


# =========================================================
# DUYỆT EMAIL
# =========================================================
def iter_all_messages(service, query=""):
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, maxResults=500, pageToken=page_token
        ).execute()
        for m in resp.get("messages", []):
            yield m["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def get_header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def walk_parts(payload):
    results, stack = [], [payload]
    while stack:
        p = stack.pop()
        if p is None:
            continue
        filename = p.get("filename")
        body = p.get("body", {})
        if filename and (body.get("attachmentId") or body.get("data")):
            results.append(p)
        for child in p.get("parts", []) or []:
            stack.append(child)
    return results


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico")


def _part_disposition(part):
    for h in part.get("headers", []) or []:
        if h.get("name", "").lower() == "content-disposition":
            return (h.get("value") or "").lower()
    return ""


def is_real_attachment(part) -> bool:
    """File đính kèm THẬT (không phải logo/ảnh nhúng inline)."""
    name = (part.get("filename") or "").strip().lower()
    if not name:
        return False
    is_image = name.endswith(IMAGE_EXTS)
    disp = _part_disposition(part)
    if is_image and not disp.startswith("attachment"):
        return False
    return True


def decode_base64url(data):
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def extract_text(payload):
    text = ""
    stack = [payload] if isinstance(payload, dict) else list(payload or [])
    while stack:
        p = stack.pop()
        if not p:
            continue
        mime = p.get("mimeType", "")
        data = (p.get("body") or {}).get("data")
        if mime in ("text/plain", "text/html") and data:
            try:
                text += decode_base64url(data).decode("utf-8", errors="ignore")
            except Exception:
                pass
        stack.extend(p.get("parts") or [])
    return text


# =========================================================
# GMAIL SERVICE (token hỏng/hết hạn -> tự xóa, đăng nhập lại)
# =========================================================
def _xoa_token(cfg: ClientConfig):
    try:
        os.remove(cfg.token_file)
        print(f"Đã xóa token cũ: {cfg.token_file}")
    except OSError:
        pass


def get_service(cfg: ClientConfig):
    creds = None
    if os.path.exists(cfg.token_file):
        try:
            creds = Credentials.from_authorized_user_file(cfg.token_file, SCOPES)
        except Exception as e:
            print("Token file hỏng:", e)
            creds = None
            _xoa_token(cfg)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            print("Refresh token thất bại (hết hạn/bị thu hồi):", e)
            creds = None
            _xoa_token(cfg)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(cfg.credentials_file, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(cfg.token_file, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# =========================================================
# QUERY
# =========================================================
def build_gmail_query(cfg: ClientConfig) -> str:
    parts = []

    if cfg.extra_query.strip():
        parts.append(cfg.extra_query.strip())

    if cfg.sender.strip():
        addrs = cfg.sender.split()
        if len(addrs) == 1:
            parts.append(f"from:{addrs[0]}")
        else:
            parts.append("from:{" + " ".join(addrs) + "}")

    if cfg.subject_keyword:
        parts.append(f'subject:"{cfg.subject_keyword}"')

    if cfg.date_from:
        y, m, d = cfg.date_from.split("-")
        parts.append(f"after:{y}/{m}/{d}")

    if cfg.date_to:
        dt = datetime.strptime(cfg.date_to, "%Y-%m-%d") + timedelta(days=1)
        parts.append(f"before:{dt.strftime('%Y/%m/%d')}")

    if not cfg.download_all:
        parts.append("is:unread")

    return " ".join(parts)


# =========================================================
# MAIN
# =========================================================
def run(cfg: ClientConfig, logger=print) -> int:
    """Chạy tải hóa đơn cho một khách. Trả về số file đã lưu."""
    service = get_service(cfg)
    gmail_query = build_gmail_query(cfg)
    logger(f"[{cfg.client_id}] QUERY: {gmail_query}")

    total_saved = 0

    for msg_id in iter_all_messages(service, gmail_query):
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        from_raw = get_header(headers, "From")
        _, from_email = parseaddr(from_raw)
        from_email = (from_email or "").lower()
        subject = get_header(headers, "Subject") or ""

        body_text = ""
        try:
            body_text = extract_text(payload)
        except Exception:
            pass

        # Chọn nơi lưu
        base_dir = choose_base_dir(from_email, cfg)
        if base_dir:
            save_dir = Path(base_dir)
        elif cfg.flat_save:
            # Lưu phẳng vào base_save_dir, không tạo thư mục con theo người gửi (TaiLoc).
            save_dir = Path(cfg.base_save_dir)
        else:
            folder_from_rules = choose_folder_by_rules(from_email, cfg.folder_rules)
            folder_name = folder_from_rules or normalize_sender_folder(from_email)
            save_dir = Path(cfg.base_save_dir) / folder_name
        save_dir.mkdir(parents=True, exist_ok=True)

        # Ưu tiên 1: file đính kèm thật
        real_atts = [p for p in walk_parts(payload) if is_real_attachment(p)]
        if real_atts:
            saved_any = False
            for part in real_atts:
                filename = safe_filename(part.get("filename"))
                body = part.get("body", {})
                data = body.get("data")
                content_bytes = None
                if data:
                    content_bytes = decode_base64url(data)
                elif body.get("attachmentId"):
                    att = service.users().messages().attachments().get(
                        userId="me", messageId=msg_id, id=body["attachmentId"]
                    ).execute()
                    content_bytes = base64.urlsafe_b64decode(att["data"].encode("utf-8"))
                if not content_bytes:
                    continue
                out_path = ensure_unique_path(save_dir / filename)
                with open(out_path, "wb") as f:
                    f.write(content_bytes)
                saved_any = True
                total_saved += 1
                logger(f"[{cfg.client_id}] ĐÃ LƯU (đính kèm): {out_path}")

            if saved_any:
                service.users().messages().modify(
                    userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
                ).execute()
            # Có đính kèm -> không chạy provider. Fail thì không đánh dấu đã đọc.
            continue

        # Tiền tố tên file theo brand (nếu khách khai brand_rules, vd TaiLoc)
        name_prefix = choose_brand_prefix(subject, cfg)

        # Ưu tiên 2: nhà cung cấp hóa đơn
        for prov_name, is_match, download_fn in PROVIDERS:
            if not is_match(subject, from_email, body_text):
                continue
            logger(f"[{cfg.client_id}] EMAIL {prov_name}: {subject}")
            # Chỉ truyền name_prefix cho provider nào hỗ trợ (vd direct_link).
            extra = {}
            if name_prefix and "name_prefix" in inspect.signature(download_fn).parameters:
                extra["name_prefix"] = name_prefix
            ok = download_fn(body_text, str(save_dir), **extra)
            if ok:
                total_saved += 1
                service.users().messages().modify(
                    userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
                ).execute()
            else:
                logger(f"[{cfg.client_id}] {prov_name}: tải fail")
            break

    logger(f"[{cfg.client_id}] HOÀN TẤT. Đã lưu {total_saved} file.")
    return total_saved


def run_with_retry(cfg: ClientConfig, logger=print) -> int:
    """Như run() nhưng nếu token chết GIỮA CHỪNG -> xóa token, chạy lại 1 lần."""
    try:
        return run(cfg, logger)
    except RefreshError:
        logger(f"[{cfg.client_id}] Token hết hạn giữa phiên -> xóa, đăng nhập lại...")
        _xoa_token(cfg)
        return run(cfg, logger)
