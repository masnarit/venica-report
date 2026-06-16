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
    """親フォルダ内から月に対応するサブフォルダIDを返す（共有ドライブ対応）"""
    query = (
        f"'{parent_id}' in parents "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    result = svc.files().list(
        q=query,
        fields="files(id,name)",
        pageSize=50,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    folders = result.get("files", [])

    candidates = set(_candidate_folder_names(year_month))
    logger.info("サブフォルダ検索: 候補名=%s", candidates)
    logger.info("サブフォルダ一覧: %s", [f["name"] for f in folders])
    for f in folders:
        if f["name"] in candidates:
            logger.info("サブフォルダ一致: %s", f["name"])
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
        .list(
            q=query,
            fields="files(id,name,createdTime,size)",
            pageSize=200,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
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


def _normalize_text(text: str) -> str:
    """PDF抽出テキストの表記ゆれを最低限ならす。"""
    return (
        text.replace("\u3000", " ")
        .replace("，", ",")
        .replace("．", ".")
        .replace("￥", "¥")
        .replace("−", "-")
        .replace("ー", "-")
        .replace("―", "-")
    )


def _amount_to_int(value: str) -> int | None:
    """金額文字列を整数に変換する。日付や小さい数字は除外する。"""
    cleaned = (
        value.replace(",", "")
        .replace("¥", "")
        .replace("円", "")
        .replace("税込", "")
        .replace("税抜", "")
        .replace("-", "")
        .strip()
    )
    if not cleaned or not re.fullmatch(r"\d+", cleaned):
        return None

    amount = int(cleaned)
    # 日付・税率・個数などの誤検知を避けるため、請求書金額として小さすぎる値は除外。
    if amount < 1000:
        return None
    return amount


def _extract_amount(text: str) -> int:
    """
    請求書金額を抽出する。
    優先順位:
      1. 「請求金額」「お支払金額」「合計（税込）」などのラベル近辺
      2. 「円」または「¥」付きの金額
      3. カンマ付きの大きな数字
    """
    normalized = _normalize_text(text)
    compact = re.sub(r"[ \t]+", " ", normalized)

    amount_number = r"(?:¥\s*)?(\d{1,3}(?:,\d{3})+|\d{4,10})(?:\s*円)?"
    label_groups = [
        ["ご請求金額", "御請求金額", "今回ご請求額", "請求金額"],
        ["お支払金額", "お振込金額", "振込金額", "支払金額"],
        ["税込合計", "合計（税込）", "合計(税込)", "総合計", "合計金額"],
        ["ご請求額", "請求額", "支払額"],
        ["合計"],
    ]

    # ラベル優先度順に探す。税抜小計や明細単価を拾いにくくするため、最初に見つかった
    # 高優先ラベル群の金額だけを採用する。
    for labels in label_groups:
        label_re = "|".join(re.escape(label) for label in labels)
        prioritized: list[int] = []

        for m in re.finditer(rf"(?:{label_re})[^\d¥]{{0,50}}{amount_number}", compact, re.IGNORECASE):
            amount = _amount_to_int(m.group(1))
            if amount:
                prioritized.append(amount)

        for m in re.finditer(rf"{amount_number}[^\d\n]{{0,25}}(?:{label_re})", compact, re.IGNORECASE):
            amount = _amount_to_int(m.group(1))
            if amount:
                prioritized.append(amount)

        if prioritized:
            return max(prioritized)

    candidates: list[int] = []

    # 「円」または「¥」付き金額を広く拾う。
    for m in re.finditer(r"(?:¥\s*)?(\d{1,3}(?:,\d{3})+|\d{4,10})\s*円|¥\s*(\d{1,3}(?:,\d{3})+|\d{4,10})", compact):
        amount = _amount_to_int(m.group(1) or m.group(2) or "")
        if amount:
            candidates.append(amount)

    # 最後の保険として、カンマ付きの数字を拾う。
    for m in re.finditer(r"\b(\d{1,3}(?:,\d{3})+)\b", compact):
        amount = _amount_to_int(m.group(1))
        if amount:
            candidates.append(amount)

    return max(candidates) if candidates else 0


def _looks_tax_exclusive_amount(text: str, amount: int) -> bool:
    """抽出した金額が税抜額らしいかを判定する。"""
    if amount <= 0:
        return False

    normalized = _normalize_text(text)
    amount_patterns = {
        f"{amount:,}",
        str(amount),
    }
    tax_exclusive_words = ["税抜", "税別", "小計", "本体価格"]
    tax_inclusive_words = ["税込", "ご請求金額", "請求金額", "お支払金額", "支払金額", "総合計"]

    for line in normalized.splitlines():
        if not any(pattern in line for pattern in amount_patterns):
            continue
        if any(word in line for word in tax_inclusive_words):
            return False
        if any(word in line for word in tax_exclusive_words):
            return True
    return False


def _extract_vendor(text: str, file_name: str) -> str:
    """請求元・支払先らしい社名を抽出する。取れない場合はファイル名を使う。"""
    lines = [l.strip() for l in _normalize_text(text).split("\n") if l.strip()]

    skip_words = ["御中", "様", "請求書", "納品書", "領収書", "見積書", "VENICA", "Venica"]
    company_words = ["株式会社", "合同会社", "有限会社", "Inc.", "CO.,LTD", "Co., Ltd", "LLC"]

    for line in lines[:30]:
        if any(word in line for word in company_words) and not any(word in line for word in skip_words):
            return line[:50]

    for line in lines[:30]:
        if any(word in line for word in company_words):
            return line[:50]

    return file_name


def parse_invoice(text: str, file_name: str = "") -> dict:
    logger.info("抽出テキスト冒頭[%s]: %s", file_name[:30], repr(text[:300]))
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
    normalized_text = _normalize_text(text)
    result = {
        "vendor": "",
        "amount": 0,
        "tax_type": "不明",
        "due_date": "",
        "category": classify_expense(normalized_text + " " + file_name),
        "raw_text": normalized_text[:500],
        "file_name": file_name,
    }

    result["amount"] = _extract_amount(normalized_text)
    if result["amount"] == 0:
        logger.warning("金額抽出失敗: %s", file_name)

    # 税区分
    if "10%" in normalized_text or "消費税10" in normalized_text:
        result["tax_type"] = "課税10%"
    elif "8%" in normalized_text or "軽減税率" in normalized_text:
        result["tax_type"] = "軽減8%"
    elif "非課税" in normalized_text or "免税" in normalized_text:
        result["tax_type"] = "非課税"

    if result["tax_type"] == "課税10%" and _looks_tax_exclusive_amount(normalized_text, result["amount"]):
        before = result["amount"]
        result["amount"] = int(round(result["amount"] * 1.1))
        logger.info("税抜額を税込補正: %s %s -> %s", file_name, before, result["amount"])

    # 支払期限
    due_patterns = [
        r"支払期限[：:]\s*(\d{4}[年/\-]\d{1,2}[月/\-]\d{1,2})",
        r"お支払期限[：:]\s*(\d{4}[年/\-]\d{1,2}[月/\-]\d{1,2})",
        r"(\d{4}年\d{1,2}月\d{1,2}日).*?まで",
    ]
    for pattern in due_patterns:
        m = re.search(pattern, normalized_text)
        if m:
            result["due_date"] = m.group(1)
            break

    result["vendor"] = _extract_vendor(normalized_text, file_name)

    return result
