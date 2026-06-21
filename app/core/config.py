"""Cấu hình cho từng khách hàng (client profile).

Thay cho việc mỗi khách một file HDDT_*.py riêng, mọi khác biệt được đưa vào
clients.json. Engine (engine.py) chỉ cần nhận một ClientConfig là chạy được.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


@dataclass
class ClientConfig:
    """Cấu hình tải hóa đơn cho MỘT khách hàng."""

    client_id: str                       # mã khách, vd "GPHUC", "GPHD", "157"
    credentials_file: str                # OAuth client của Google (bí mật)
    token_file: str                      # token đã cấp quyền (bí mật)
    root_dir: str                        # thư mục gốc lưu; hỗ trợ token {date}
    date_from: str = ""                  # "YYYY-MM-DD" hoặc "" = không giới hạn
    date_to: str = ""                    # "YYYY-MM-DD" hoặc ""
    sender: str = ""                     # lọc người gửi (cách nhau bởi dấu cách)
    subject_keyword: str = ""            # lọc theo tiêu đề
    download_all: bool = False           # True = tải tất cả; False = chỉ chưa đọc
    # path_rules: người gửi -> đường dẫn lưu RIÊNG (tuyệt đối). Mỗi phần tử:
    #   {"kind": "email|domain|regex", "pattern": "...", "path": r"...\\{date}"}
    path_rules: List[Dict[str, str]] = field(default_factory=list)
    # folder_rules: người gửi -> TÊN THƯ MỤC con (trong root). Mỗi phần tử:
    #   {"kind": "email|domain|regex", "pattern": "...", "folder": "TEN-THU-MUC"}
    folder_rules: List[Dict[str, str]] = field(default_factory=list)

    # ---- Tùy chọn nâng cao (cho các khách di cư từ script cũ) ----
    # Chuỗi ghép THÊM vào đầu query Gmail, vd "has:attachment" (EMECC).
    extra_query: str = ""
    # True  -> lưu vào root_dir/'<datefrom>_to_<dateto>' (mặc định, như GPHUC).
    # False -> lưu thẳng root_dir (EMECC, TaiLoc).
    use_date_subfolder: bool = True
    # True  -> lưu PHẲNG vào base_save_dir, KHÔNG tạo thư mục con theo người gửi (TaiLoc).
    # False -> lưu vào base_save_dir/<folder_rule | tên người gửi> (mặc định, EMECC).
    flat_save: bool = False
    # brand_rules: đặt TIỀN TỐ tên file theo từ khóa trong tiêu đề (TaiLoc). Mỗi phần tử:
    #   {"keyword": "ACECOOK", "prefix": "ACECOOK"} -> file thành ACECOOK_<số>.pdf
    brand_rules: List[Dict[str, str]] = field(default_factory=list)
    # Tiền tố dùng khi có brand_rules nhưng không khớp từ khóa nào (vd "HD").
    brand_default: str = ""

    # ---- Đường dẫn dẫn xuất ----
    def expand_tokens(self, text: str) -> str:
        """Thay token {date}/{datefrom}/{dateto} trong một chuỗi đường dẫn."""
        return (
            text.replace("{date}", datetime.now().strftime("%Y%m%d"))
            .replace("{datefrom}", self.date_from)
            .replace("{dateto}", self.date_to)
        )

    @property
    def base_save_dir(self) -> str:
        """Thư mục lưu mặc định.

        - use_date_subfolder=True  -> root_dir / '<datefrom>_to_<dateto>'
        - use_date_subfolder=False -> chính root_dir
        """
        root = self.expand_tokens(self.root_dir)
        if self.use_date_subfolder and self.date_from and self.date_to:
            sub = f"{self.date_from}_to_{self.date_to}"
            return os.path.join(root, sub)
        return root


def _to_bool(value) -> bool:
    """Chấp nhận True/False, hoặc chuỗi 'YES'/'NO' (tương thích code cũ)."""
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() in {"YES", "TRUE", "1"}


def load_clients(json_path: str) -> Dict[str, ClientConfig]:
    """Nạp toàn bộ khách từ clients.json -> {client_id: ClientConfig}."""
    with open(json_path, "r", encoding="utf-8-sig") as f:
        raw = json.load(f)

    clients: Dict[str, ClientConfig] = {}
    for client_id, data in raw.items():
        clients[client_id] = ClientConfig(
            client_id=client_id,
            credentials_file=data["credentials_file"],
            token_file=data["token_file"],
            root_dir=data["root_dir"],
            date_from=data.get("date_from", ""),
            date_to=data.get("date_to", ""),
            sender=data.get("sender", ""),
            subject_keyword=data.get("subject_keyword", ""),
            download_all=_to_bool(data.get("download_all", False)),
            path_rules=data.get("path_rules", []),
            folder_rules=data.get("folder_rules", []),
            extra_query=data.get("extra_query", ""),
            use_date_subfolder=data.get("use_date_subfolder", True),
            flat_save=data.get("flat_save", False),
            brand_rules=data.get("brand_rules", []),
            brand_default=data.get("brand_default", ""),
        )
    return clients


def load_client(json_path: str, client_id: str) -> ClientConfig:
    """Nạp đúng MỘT khách. Báo lỗi rõ ràng nếu không tìm thấy."""
    clients = load_clients(json_path)
    if client_id not in clients:
        available = ", ".join(sorted(clients)) or "(trống)"
        raise KeyError(
            f"Không tìm thấy khách '{client_id}' trong {json_path}. "
            f"Hiện có: {available}"
        )
    return clients[client_id]
