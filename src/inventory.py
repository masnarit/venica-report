"""
在庫計算ロジック

VenicaではShopifyとOPENLOGIを意図的に非同期運用。
OPENLOGI在庫 - 調整値 = 実販売可能在庫 として計算する。
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

import config

logger = logging.getLogger(__name__)

ADJUSTMENT_KEYS = [
    "popup_reserved",
    "photo_loan",
    "pr_loan",
    "wholesale_reserved",
    "defective",
    "return_checking",
    "internal_reserved",
]

ADJUSTMENT_LABELS = {
    "popup_reserved": "POPUP引当",
    "photo_loan": "撮影貸出",
    "pr_loan": "PR貸出",
    "wholesale_reserved": "卸引当",
    "defective": "不良",
    "return_checking": "返品確認中",
    "internal_reserved": "社内確保",
}


@dataclass
class SkuInventory:
    sku: str
    product_name: str = ""
    category: str = "other"
    openlogi_stock: int = 0
    shopify_stock: int = 0
    adjustments: dict[str, int] = field(default_factory=dict)

    @property
    def total_adjustment(self) -> int:
        return sum(self.adjustments.get(k, 0) for k in ADJUSTMENT_KEYS)

    @property
    def available_stock(self) -> int:
        """実販売可能在庫 = OPENLOGI在庫 - 調整値合計"""
        return max(0, self.openlogi_stock - self.total_adjustment)

    @property
    def stock_diff(self) -> int:
        """ShopifyとOPENLOGIの差異（参考値）"""
        return self.openlogi_stock - self.shopify_stock

    @property
    def stock_diff_pct(self) -> float:
        if self.openlogi_stock == 0:
            return 0.0
        return abs(self.stock_diff) / self.openlogi_stock * 100


def build_inventory_table(
    openlogi_stocks: dict[str, int],
    shopify_stocks: dict[str, int],
    adjustments: dict[str, dict[str, int]],
    product_master: dict[str, dict[str, str]],
) -> list[SkuInventory]:
    """
    各データソースを統合してSKU別在庫テーブルを構築する。
    """
    all_skus = set(openlogi_stocks.keys()) | set(shopify_stocks.keys())
    result: list[SkuInventory] = []

    for sku in sorted(all_skus):
        master = product_master.get(sku, {})
        inv = SkuInventory(
            sku=sku,
            product_name=master.get("product_name", ""),
            category=master.get("category", "other"),
            openlogi_stock=openlogi_stocks.get(sku, 0),
            shopify_stock=shopify_stocks.get(sku, 0),
            adjustments=adjustments.get(sku, {}),
        )
        result.append(inv)

    return result


def detect_alerts(inventory_table: list[SkuInventory], sku_sales: dict[str, int]) -> dict[str, list[dict]]:
    """
    在庫アラートを検出する。

    Returns:
        {
            "stockout_risk": [...],    欠品リスク
            "stagnant": [...],         滞留在庫（sku_salesに登場しないSKU）
            "large_diff": [...],       在庫差異が閾値超過
        }
    """
    alerts: dict[str, list[dict]] = {
        "stockout_risk": [],
        "stagnant": [],
        "large_diff": [],
    }

    for inv in inventory_table:
        if inv.openlogi_stock == 0 and inv.shopify_stock == 0:
            continue

        # 欠品リスク：実販売可能在庫がアラート閾値以下
        daily_sales = sku_sales.get(inv.sku, 0) / 30  # 直近30日の日平均
        if daily_sales > 0:
            days_of_stock = inv.available_stock / daily_sales
            if days_of_stock <= config.STOCK_ALERT_DAYS:
                alerts["stockout_risk"].append({
                    "sku": inv.sku,
                    "product_name": inv.product_name,
                    "available_stock": inv.available_stock,
                    "days_of_stock": round(days_of_stock, 1),
                    "daily_sales": round(daily_sales, 1),
                })
        elif inv.available_stock == 0 and inv.openlogi_stock > 0:
            # 在庫はあるが調整で実販売可能数が0
            alerts["stockout_risk"].append({
                "sku": inv.sku,
                "product_name": inv.product_name,
                "available_stock": 0,
                "days_of_stock": 0,
                "daily_sales": 0,
                "note": f"調整値による引当: {inv.total_adjustment}点",
            })

        # 滞留在庫：販売がなく在庫がある
        if inv.openlogi_stock > 0 and sku_sales.get(inv.sku, 0) == 0:
            alerts["stagnant"].append({
                "sku": inv.sku,
                "product_name": inv.product_name,
                "openlogi_stock": inv.openlogi_stock,
                "available_stock": inv.available_stock,
            })

        # 在庫差異アラート
        if inv.stock_diff_pct >= config.STOCK_DIFF_THRESHOLD and abs(inv.stock_diff) >= 5:
            alerts["large_diff"].append({
                "sku": inv.sku,
                "product_name": inv.product_name,
                "openlogi_stock": inv.openlogi_stock,
                "shopify_stock": inv.shopify_stock,
                "diff": inv.stock_diff,
                "diff_pct": round(inv.stock_diff_pct, 1),
            })

    return alerts
