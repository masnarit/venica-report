"""
設定値・環境変数の読み込み
全モジュールはここからconfigをimportする
"""
import os
import base64
import json
import tempfile
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"必須の環境変数が設定されていません: {key}")
    return val


# --- Shopify ---
SHOPIFY_SHOP_DOMAIN = _require("SHOPIFY_SHOP_DOMAIN")
SHOPIFY_ACCESS_TOKEN = _require("SHOPIFY_ACCESS_TOKEN")

# --- OPENLOGI ---
OPENLOGI_API_KEY = _require("OPENLOGI_API_KEY")
OPENLOGI_WAREHOUSE_ID = os.getenv("OPENLOGI_WAREHOUSE_ID", "")

# --- Google ---
GOOGLE_SPREADSHEET_ID = _require("GOOGLE_SPREADSHEET_ID")
GMAIL_SENDER = _require("GMAIL_SENDER")
GMAIL_RECIPIENTS = [e.strip() for e in _require("GMAIL_RECIPIENTS").split(",")]

# --- Claude API ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- アラート閾値 ---
STOCK_ALERT_DAYS = int(os.getenv("STOCK_ALERT_DAYS", "3"))
STAGNANT_STOCK_DAYS = int(os.getenv("STAGNANT_STOCK_DAYS", "30"))
STOCK_DIFF_THRESHOLD = float(os.getenv("STOCK_DIFF_THRESHOLD", "10"))

# --- タイムゾーン ---
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tokyo")

# --- Google サービスアカウント ---
def get_service_account_path() -> str:
    """
    GOOGLE_SERVICE_ACCOUNT_JSON_B64からJSONファイルを一時生成して返す。
    GitHub ActionsのSecretsでJSONをBase64エンコードして保存する方式に対応。
    """
    b64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64")
    if b64:
        decoded = base64.b64decode(b64 + "==")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="wb")
        tmp.write(decoded)
        tmp.close()
        return tmp.name

    # ローカル開発用：service_account.jsonが直接置かれている場合
    local_path = os.path.join(os.path.dirname(__file__), "..", "service_account.json")
    if os.path.exists(local_path):
        return os.path.abspath(local_path)

    raise EnvironmentError(
        "Google認証情報が見つかりません。"
        "GOOGLE_SERVICE_ACCOUNT_JSON_B64 を設定するか、"
        "service_account.json を配置してください。"
    )


# --- Sheets シート名 ---
SHEET_INVENTORY_ADJUSTMENTS = "inventory_adjustments"
SHEET_SALES_TARGETS = "sales_targets"
SHEET_PRODUCT_MASTER = "product_master"
SHEET_CS_KEYWORDS = "cs_keywords"
SHEET_REPORT_LOG = "report_log"
