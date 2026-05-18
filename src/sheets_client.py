"""
Google Sheets 読み書きクライアント
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _build_service():
    creds = service_account.Credentials.from_service_account_file(
        config.get_service_account_path(), scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def read_sheet(sheet_name: str, range_suffix: str = "") -> list[list[str]]:
    """指定シートの全データを2次元リストで返す"""
    svc = _build_service()
    range_name = f"{sheet_name}!A:Z" if not range_suffix else f"{sheet_name}!{range_suffix}"
    result = (
        svc.spreadsheets()
        .values()
        .get(spreadsheetId=config.GOOGLE_SPREADSHEET_ID, range=range_name)
        .execute()
    )
    return result.get("values", [])


def append_row(sheet_name: str, row: list[Any]) -> None:
    """シートの末尾に1行追記する"""
    svc = _build_service()
    svc.spreadsheets().values().append(
        spreadsheetId=config.GOOGLE_SPREADSHEET_ID,
        range=f"{sheet_name}!A:A",
        valueInputOption="USER_ENTERED",
        body={"values": [row]},
    ).execute()


def write_log(report_type: str, status: str, message: str = "") -> None:
    """実行ログをreport_logシートに記録"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [now, report_type, status, message, ",".join(config.GMAIL_RECIPIENTS)]
    try:
        append_row(config.SHEET_REPORT_LOG, row)
    except Exception as e:
        logger.warning("ログ書き込み失敗（無視して継続）: %s", e)


def get_inventory_adjustments() -> dict[str, dict[str, int]]:
    """
    在庫調整テーブルを読み込んでSKUをキーにした辞書を返す。
    戻り値例: {"SKU-001": {"popup_reserved": 5, "photo_loan": 2, ...}}
    """
    rows = read_sheet(config.SHEET_INVENTORY_ADJUSTMENTS)
    if not rows or len(rows) < 2:
        return {}

    header = rows[0]
    adjustments: dict[str, dict[str, int]] = {}

    for row in rows[1:]:
        if not row:
            continue
        sku = row[0].strip() if len(row) > 0 else ""
        if not sku:
            continue

        def _int(idx: int) -> int:
            try:
                return int(row[idx]) if len(row) > idx and row[idx] else 0
            except ValueError:
                return 0

        adjustments[sku] = {
            "popup_reserved": _int(2),
            "photo_loan": _int(3),
            "pr_loan": _int(4),
            "wholesale_reserved": _int(5),
            "defective": _int(6),
            "return_checking": _int(7),
            "internal_reserved": _int(8),
        }

    return adjustments


def get_sales_target(year_month: str) -> int:
    """YYYY-MM形式で月次目標売上を返す。未設定なら0。"""
    rows = read_sheet(config.SHEET_SALES_TARGETS)
    for row in rows[1:]:
        if len(row) >= 2 and row[0].strip() == year_month:
            try:
                val = str(row[1]).replace(",", "").replace("¥", "").replace("$", "").strip()
                return int(float(val))
            except ValueError:
                return 0
    return 0


def get_product_master() -> dict[str, dict[str, str]]:
    """商品マスタをSKUをキーにした辞書で返す"""
    rows = read_sheet(config.SHEET_PRODUCT_MASTER)
    if not rows or len(rows) < 2:
        return {}

    master: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        if not row:
            continue
        sku = row[0].strip() if len(row) > 0 else ""
        if not sku:
            continue
        master[sku] = {
            "product_name": row[1] if len(row) > 1 else "",
            "category": row[2] if len(row) > 2 else "other",
            "price": row[3] if len(row) > 3 else "0",
            "launch_date": row[4] if len(row) > 4 else "",
        }
    return master


def get_cs_keywords() -> dict[str, list[str]]:
    """CS分類キーワード辞書を返す"""
    rows = read_sheet(config.SHEET_CS_KEYWORDS)
    keywords: dict[str, list[str]] = {}
    for row in rows[1:]:
        if len(row) >= 2 and row[0] and row[1]:
            cat = row[0].strip()
            kws = [k.strip() for k in row[1].split(",") if k.strip()]
            keywords[cat] = kws
    return keywords
