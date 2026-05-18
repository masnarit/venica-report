"""
週次CSレビュー バッチスクリプト

毎週月曜9時（JST）にGitHub Actionsから実行される。
前週のCS問い合わせをGmailから取得・分類してレポートを送信する。
"""
from __future__ import annotations
import base64
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from jinja2 import Environment, FileSystemLoader
from google.oauth2 import service_account
from googleapiclient.discovery import build

import config
import cs_classifier
import gmail_client
import sheets_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TZ = pytz.timezone(config.TIMEZONE)
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _build_gmail_service():
    creds = service_account.Credentials.from_service_account_file(
        config.get_service_account_path(), scopes=GMAIL_SCOPES
    ).with_subject(config.GMAIL_SENDER)
    return build("gmail", "v1", credentials=creds)


def fetch_cs_emails(date_from: datetime, date_to: datetime) -> list[cs_classifier.CsTicket]:
    """
    Gmailからお問い合わせメールを取得する。

    運用方法：
    - CS問い合わせを受けるGmailアカウントをGMAIL_SENDERと同一ドメインで設定
    - または問い合わせをCSVでGoogleDriveに置く方式にも対応（fetch_cs_from_csv参照）
    """
    svc = _build_gmail_service()

    after_ts = int(date_from.timestamp())
    before_ts = int(date_to.timestamp())
    query = f"after:{after_ts} before:{before_ts} in:inbox"

    tickets: list[cs_classifier.CsTicket] = []

    try:
        result = svc.users().messages().list(userId="me", q=query, maxResults=500).execute()
        messages = result.get("messages", [])

        for msg_ref in messages:
            msg = svc.users().messages().get(
                userId="me", id=msg_ref["id"], format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            subject = headers.get("Subject", "（件名なし）")
            date_str = headers.get("Date", "")

            body = _extract_body(msg.get("payload", {}))

            tickets.append(cs_classifier.CsTicket(
                ticket_id=msg_ref["id"],
                subject=subject,
                body=body[:500],
                date=date_str,
            ))

    except Exception as e:
        logger.warning("Gmail取得失敗（空リスト返却）: %s", e)

    return tickets


def _extract_body(payload: dict) -> str:
    """メール本文を抽出"""
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    return ""


def run() -> None:
    now = datetime.now(TZ)
    week_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = week_end - timedelta(days=7)

    logger.info("=== 週次CSレビュー開始: %s〜%s ===", week_start.strftime("%m/%d"), week_end.strftime("%m/%d"))

    # 今週のチケット
    tickets_this_week = fetch_cs_emails(week_start, week_end)
    classified_this = cs_classifier.classify_tickets(tickets_this_week)
    agg_this = cs_classifier.aggregate(classified_this)

    # 先週のチケット（前週比用）
    prev_start = week_start - timedelta(days=7)
    tickets_prev = fetch_cs_emails(prev_start, week_start)
    classified_prev = cs_classifier.classify_tickets(tickets_prev)
    agg_prev = cs_classifier.aggregate(classified_prev)

    # 前週比計算
    comparison = []
    all_cats = sorted(
        set(list(agg_this.keys()) + list(agg_prev.keys())),
        key=lambda c: agg_this.get(c, {}).get("count", 0),
        reverse=True,
    )
    for cat in all_cats:
        this_count = agg_this.get(cat, {}).get("count", 0)
        prev_count = agg_prev.get(cat, {}).get("count", 0)
        change = this_count - prev_count
        sample_tickets = agg_this.get(cat, {}).get("tickets", [])[:3]
        comparison.append({
            "category": cat,
            "this_count": this_count,
            "prev_count": prev_count,
            "change": change,
            "samples": [{"subject": t.subject, "date": t.date} for t in sample_tickets],
        })

    total_this = len(classified_this)
    total_prev = len(classified_prev)

    # HTMLレポート生成
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("weekly_cs.html")

    html = template.render(
        week_start=week_start.strftime("%Y/%m/%d"),
        week_end=(week_end - timedelta(days=1)).strftime("%Y/%m/%d"),
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        total_this=total_this,
        total_prev=total_prev,
        total_change=total_this - total_prev,
        comparison=comparison,
    )

    subject = f"【Venica】週次CSレビュー（{week_start.strftime('%m/%d')}〜{(week_end - timedelta(days=1)).strftime('%m/%d')}）"
    gmail_client.send_html_email(subject, html)

    sheets_client.write_log("weekly_cs", "success")
    logger.info("=== 週次CSレビュー完了 ===")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.exception("週次CSレビュー失敗: %s", e)
        try:
            sheets_client.write_log("weekly_cs", "error", str(e))
        except Exception:
            pass
        sys.exit(1)
