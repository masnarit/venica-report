"""
OPENLOGI API クライアント

公式ドキュメント: https://api.openlogi.com/docs
APIキーはOPENLOGI管理画面の「API設定」から取得してください。

重要：VenicaではOPENLOGI在庫は「在庫の基準値」として使用し、
      在庫調整テーブルで実販売可能在庫を算出します。
"""
from __future__ import annotations
import logging
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openlogi.com/api"
HEADERS = {
    "Authorization": f"Bearer {config.OPENLOGI_API_KEY}",
    "Content-Type": "application/json",
}


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}/{path}"
    resp = requests.get(url, headers=HEADERS, params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_inventory() -> dict[str, int]:
    """
    SKUをキーにした在庫数辞書を返す。

    OPENLOGIのAPIレスポンス構造に合わせて適宜調整してください。
    APIが利用できない場合は空辞書を返します（フォールバック）。
    """
    try:
        params = {}
        if config.OPENLOGI_WAREHOUSE_ID:
            params["warehouse_id"] = config.OPENLOGI_WAREHOUSE_ID

        data = _get("inventories", params)
        inventory: dict[str, int] = {}

        items = data.get("inventories", data.get("items", data.get("data", [])))
        for item in items:
            sku = (item.get("sku") or item.get("code") or "").strip()
            qty = int(item.get("quantity", item.get("stock", 0)) or 0)
            if sku:
                inventory[sku] = inventory.get(sku, 0) + qty

        logger.info("OPENLOGI在庫取得: %d SKU", len(inventory))
        return inventory

    except requests.HTTPError as e:
        logger.error("OPENLOGI API エラー: %s", e)
        return {}
    except Exception as e:
        logger.error("OPENLOGI 在庫取得失敗: %s", e)
        return {}


def get_inbound_histories(days: int = 30) -> list[dict]:
    """
    直近N日間の入庫履歴を取得（在庫差異分析用）。
    APIが対応していない場合は空リストを返します。
    """
    try:
        data = _get("inbound_histories", {"days": days})
        return data.get("histories", data.get("data", []))
    except Exception as e:
        logger.warning("入庫履歴取得失敗（無視して継続）: %s", e)
        return []
