"""
Shopify Admin API クライアント
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Any

import requests
import pytz

import config

logger = logging.getLogger(__name__)

TZ = pytz.timezone(config.TIMEZONE)
BASE_URL = f"https://{config.SHOPIFY_SHOP_DOMAIN}/admin/api/2024-01"
HEADERS = {
    "X-Shopify-Access-Token": config.SHOPIFY_ACCESS_TOKEN,
    "Content-Type": "application/json",
}


def _get(endpoint: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _paginate(endpoint: str, key: str, params: dict | None = None) -> list[dict]:
    """Link headerを使ってページネーション対応で全件取得"""
    results: list[dict] = []
    url = f"{BASE_URL}/{endpoint}"
    p = dict(params or {})
    p.setdefault("limit", 250)

    while url:
        resp = requests.get(url, headers=HEADERS, params=p, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get(key, []))

        link = resp.headers.get("Link", "")
        url = None
        p = {}
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part.strip().split(";")[0].strip().strip("<>")
                break

    return results


def get_orders(date_from: datetime, date_to: datetime) -> list[dict]:
    """指定期間の注文一覧を取得"""
    params = {
        "created_at_min": date_from.isoformat(),
        "created_at_max": date_to.isoformat(),
        "status": "any",
        "financial_status": "paid",
    }
    return _paginate("orders.json", "orders", params)


def get_yesterday_orders() -> list[dict]:
    now = datetime.now(TZ)
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday_start.replace(hour=23, minute=59, second=59)
    return get_orders(yesterday_start, yesterday_end)


def get_month_to_date_orders() -> list[dict]:
    now = datetime.now(TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return get_orders(month_start, now)


def get_orders_in_days(days: int) -> list[dict]:
    """直近N日間の注文を取得（初速分析用）"""
    now = datetime.now(TZ)
    start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    return get_orders(start, now)


def get_inventory_levels() -> dict[str, int]:
    """
    VariantのInventory Item IDをキーにした在庫数辞書を返す。
    Shopify在庫は参考値として使用（OPENLOGI在庫が正）。
    """
    variants = _paginate("variants.json", "variants")
    inventory_item_ids = [str(v["inventory_item_id"]) for v in variants if v.get("inventory_item_id")]

    # 250件ずつ取得
    levels: dict[str, int] = {}
    chunk_size = 50
    for i in range(0, len(inventory_item_ids), chunk_size):
        chunk = inventory_item_ids[i:i + chunk_size]
        resp = _get("inventory_levels.json", {"inventory_item_ids": ",".join(chunk)})
        for level in resp.get("inventory_levels", []):
            iid = str(level["inventory_item_id"])
            levels[iid] = levels.get(iid, 0) + (level.get("available") or 0)

    return levels


def get_inventory_by_sku() -> dict[str, int]:
    """SKUをキーにしたShopify在庫辞書を返す"""
    variants = _paginate("variants.json", "variants")
    inv_levels = get_inventory_levels()

    sku_inventory: dict[str, int] = {}
    for v in variants:
        sku = v.get("sku", "").strip()
        iid = str(v.get("inventory_item_id", ""))
        if sku and iid in inv_levels:
            sku_inventory[sku] = sku_inventory.get(sku, 0) + inv_levels[iid]

    return sku_inventory


def calc_sales_kpi(orders: list[dict]) -> dict[str, Any]:
    """注文リストからKPIを計算"""
    if not orders:
        return {
            "total_revenue": 0,
            "order_count": 0,
            "buyer_count": 0,
            "avg_order_value": 0,
        }

    total_revenue = sum(float(o.get("total_price", 0)) for o in orders)
    order_count = len(orders)
    buyer_emails = {o.get("email", "") for o in orders if o.get("email")}
    buyer_count = len(buyer_emails)
    avg_order_value = total_revenue / order_count if order_count else 0

    return {
        "total_revenue": int(total_revenue),
        "order_count": order_count,
        "buyer_count": buyer_count,
        "avg_order_value": int(avg_order_value),
    }


def calc_sku_sales(orders: list[dict]) -> dict[str, int]:
    """注文リストからSKU別販売数を集計"""
    sku_count: dict[str, int] = {}
    for order in orders:
        for item in order.get("line_items", []):
            sku = item.get("sku", "").strip()
            qty = int(item.get("quantity", 0))
            if sku:
                sku_count[sku] = sku_count.get(sku, 0) + qty
    return sku_count
