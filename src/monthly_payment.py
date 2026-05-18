"""
月次支払集計 バッチスクリプト

毎月1日9時（JST）にGitHub Actionsから実行される。
Google Drive内の請求書PDFをOCR解析して月次集計レポートを送信する。
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from jinja2 import Environment, FileSystemLoader

import config
import drive_client
import gmail_client
import sheets_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TZ = pytz.timezone(config.TIMEZONE)
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

# 請求書PDFが格納されているGoogle DriveフォルダID
# 環境変数INVOICE_FOLDER_IDで設定、またはconfig.py側で管理
INVOICE_FOLDER_ID = os.getenv("INVOICE_FOLDER_ID", "")


def run() -> None:
    now = datetime.now(TZ)
    # 先月を集計対象にする
    first_of_this_month = now.replace(day=1)
    last_month = first_of_this_month - timedelta(days=1)
    year_month = last_month.strftime("%Y-%m")

    logger.info("=== 月次支払集計開始: %s ===", year_month)

    if not INVOICE_FOLDER_ID:
        raise EnvironmentError(
            "INVOICE_FOLDER_ID が未設定です。"
            "請求書PDFのGoogle DriveフォルダIDを環境変数に設定してください。"
        )

    # PDFファイル一覧取得
    pdf_files = drive_client.list_invoices_in_folder(INVOICE_FOLDER_ID, year_month)
    logger.info("対象PDFファイル数: %d", len(pdf_files))

    # 各PDFを解析
    invoices: list[dict] = []
    errors: list[dict] = []

    for f in pdf_files:
        try:
            logger.info("解析中: %s", f["name"])
            pdf_bytes = drive_client.download_pdf(f["id"])
            text = drive_client.extract_text_from_pdf(pdf_bytes)
            invoice = drive_client.parse_invoice(text, f["name"])
            invoices.append(invoice)
        except Exception as e:
            logger.warning("PDF解析失敗 %s: %s", f["name"], e)
            errors.append({"file_name": f["name"], "error": str(e)})

    # カテゴリ別集計
    category_totals: dict[str, int] = {}
    category_items: dict[str, list[dict]] = {}

    for inv in invoices:
        cat = inv["category"]
        amount = inv["amount"]
        category_totals[cat] = category_totals.get(cat, 0) + amount
        if cat not in category_items:
            category_items[cat] = []
        category_items[cat].append(inv)

    total_amount = sum(category_totals.values())

    # カテゴリを定義順でソート
    category_order = list(drive_client.EXPENSE_CATEGORIES.keys())
    sorted_categories = sorted(
        category_totals.items(),
        key=lambda x: category_order.index(x[0]) if x[0] in category_order else 99,
    )

    # HTMLレポート生成
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("monthly_payment.html")

    html = template.render(
        year_month=year_month,
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        total_amount=total_amount,
        pdf_count=len(pdf_files),
        invoice_count=len(invoices),
        error_count=len(errors),
        sorted_categories=sorted_categories,
        category_items=category_items,
        errors=errors,
    )

    subject = f"【Venica】{year_month} 月次支払集計レポート"
    gmail_client.send_html_email(subject, html)

    sheets_client.write_log("monthly_payment", "success", f"請求書{len(invoices)}件 合計{total_amount:,}円")
    logger.info("=== 月次支払集計完了: 合計%d件 %s円 ===", len(invoices), f"{total_amount:,}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.exception("月次支払集計失敗: %s", e)
        try:
            sheets_client.write_log("monthly_payment", "error", str(e))
        except Exception:
            pass
        sys.exit(1)
