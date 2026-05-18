"""
Gmail API クライアント（HTMLメール送信）
"""
from __future__ import annotations
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2 import service_account
from googleapiclient.discovery import build

import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _build_service():
    creds = service_account.Credentials.from_service_account_file(
        config.get_service_account_path(), scopes=SCOPES
    )
    # ドメイン委任：送信元アドレスに成り代わる
    delegated = creds.with_subject(config.GMAIL_SENDER)
    return build("gmail", "v1", credentials=delegated)


def send_html_email(subject: str, html_body: str, recipients: list[str] | None = None) -> None:
    """
    HTML形式のメールを送信する。
    recipients省略時はconfig.GMAIL_RECIPIENTSに送信。
    """
    to_list = recipients or config.GMAIL_RECIPIENTS

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_SENDER
    msg["To"] = ", ".join(to_list)

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    svc = _build_service()
    svc.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()

    logger.info("メール送信完了: subject=%s to=%s", subject, to_list)
