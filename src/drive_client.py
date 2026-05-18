"""
Google Drive APIクライアント + 請求書PDFテキスト抽出

月次支払集計で使用。PDFをダウンロードしてテキストを抽出する。
"""
from __future__ import annotations
import io
import logging
import re
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _build_service():
    creds = service_account.Credentials.from_service_account_file(
        config.get_service_account_path(), scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _candidate_folder_names(year_month: str) -> list[str]:
    """YYYY-MM から考えられるフォルダ名のパターン一覧を返す"""
    try:
        dt = datetime.strptime(year_month, "%Y-%m")
    except ValueError:
        return [year_month]

    yy = dt.strftime("%y")   # "26"
    mm = str(dt.month)       # "5" (ゼロなし)
    mm0 = dt.strftime("%m")  # "05" (ゼロあり)

    return [
        year_month,                      # 2026-05
        f"{yy}年{mm}月払い",              # 26年5月払い
        f"{yy}年{mm0}月払い",             # 26年05月払い
        f"{dt.year}年{mm}月払い",         # 2026年5月払い
        f"{dt.year}年{mm}月",            # 2026年5月
        f"{yy}{mm0}",                    # 2605
    ]


def _find_subfolder(svc, parent_id: str, year_month: str) -> str | None:
    """親フォルダ内から月に対応するサブフォルダIDを返す"""
    query = (
        f"'{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    result = svc.files().list(q=query, fields="files(id,name)", pageSize=50).execute()
    folders = result.get("files", [])

    candidates = set(_candidate_folder_names(year_month))
    for f in folders:
        if f["name"] in candidates:
            return f["id"]
    return None


def list_invoices_in_folder(folder_id: str, year_month: str) -> list[dict]:
    """
    月別サブフォルダ内のPDFファイル一覧を返す。
    「26年5月払い」「2026-05」など複数の命名形式に対応。
    """
    svc = _build_service()

    target_folder = _find_subfolder(svc, folder_id, year_month)
    search_folder = target_folder or folder_id

    query = f"'{search_folder}' in parents and mimeType='application/pdf' and trashed=false"
    result = (
        svc.files()
        .list(q=query, fields="files(id,name,createdTime,size)", pageSize=200)
        .execute()
    )
    files = result.get("files", [])

    if not target_folder:
        ym_compact = year_month.replace("-", "")
        filtered = [
            f for f in files
            if year_month in f["name"] or ym_compact in f["name"].replace("-", "")
        ]
        return filtered if filtered else files

    return files


def download_pdf(file_id: str) -> bytes:
    """Google DriveからPDFをダウンロードしてbytesで返す"""
    svc = _build_service()
    request = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    PDFからテキストを抽出する。
    pypdf2またはpdfplumberを使用。どちらもない場合はエラー。
    """
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass

    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass

    raise ImportError(
        "PDFテキスト抽出ライブラリが見つかりません。"
        "pip install pdfplumber または pip install pypdf を実行してください。"
    )


# --- 請求書パーサー ---

EXPENSE_CATEGORIES = {
    "OEM": ["OEM", "縫製", "製造"],
    "生地": ["生地", "テキスタイル", "fabric"],
    "副資材": ["副資材", "ボタン", "ファスナー", "タグ"],
    "物流": ["物流", "配送", "運送", "倉庫", "OPENLOGI", "オープンロジ"],
    "広告": ["広告", "SNS", "Instagram", "Meta", "Google"],
    "SaaS": ["Shopify", "SaaS", "サブスク", "ライセンス"],
    "業務委託": ["業務委託", "フリーランス", "外注"],
    "家賃": ["家賃", "賃料", "オフィス"],
    "その他": [],
}


def classify_expense(text: str) -> str:
    """請求書テキストから費目カテゴリを判定"""
    for cat, keywords in EXPENSE_CATEGORIES.items():
        if cat == "その他":
            continue
        for kw in keywords:
            if kw.lower() in text.lower():
                return cat
    return "その他"


def parse_invoice(text: str, file_name: str = "") -> dict:
    """
    請求書テキストから必要情報を抽出する。

    返り値:
        {
            "vendor": 支払先,
            "amount": 金額（整数・税込）,
            "tax_type": 税区分,
            "due_date": 支払期限,
            "category": 費目カテゴリ,
            "raw_text": テキスト全文（確認用）
        }
    """
    result = {
        "vendor": "",
        "amount": 0,
        "tax_type": "不明",
        "due_date": "",
        "category": classify_expense(text + " " + file_name),
        "raw_text": text[:500],
        "file_name": file_name,
    }

    # 金額抽出（最大の数字を合計金額とみなす）
    amounts = re.findall(r"[¥￥]?\s*([\d,]+)\s*円", text)
    if amounts:
        nums = [int(a.replace(",", "")) for a in amounts]
        result["amount"] = max(nums)

    # 税区分
    if "10%" in text or "消費税10" in text:
        result["tax_type"] = "課税10%"
    elif "8%" in text or "軽減税率" in text:
        result["tax_type"] = "軽減8%"
    elif "非課税" in text or "免税" in text:
        result["tax_type"] = "非課税"

    # 支払期限
    due_patterns = [
        r"支払期限[：:]\s*(\d{4}[年/\-]\d{1,2}[月/\-]\d{1,2})",
        r"お支払期限[：:]\s*(\d{4}[年/\-]\d{1,2}[月/\-]\d{1,2})",
        r"(\d{4}年\d{1,2}月\d{1,2}日).*?まで",
    ]
    for pattern in due_patterns:
        m = re.search(pattern, text)
        if m:
            result["due_date"] = m.group(1)
            break

    # 請求元（宛先の上に書いてある社名を推定）
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines[:20]):
        if "株式会社" in line or "合同会社" in line or "有限会社" in line:
            result["vendor"] = line[:50]
            break

    return result
