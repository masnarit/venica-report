"""
日次経営レポート バッチスクリプト

毎朝9時（JST）にGitHub Actionsから実行される。
前日の売上・在庫データを集計してGmailでHTMLレポートを送信する。
"""
from __future__ import annotations
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz
from jinja2 import Environment, FileSystemLoader

import config
import shopify_client
import openlogi_client
import inventory as inv_module
import sheets_client
import gmail_client
import ai_comment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

TZ = pytz.timezone(config.TIMEZONE)
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def run() -> None:
    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")
    yesterday = now - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    year_month = now.strftime("%Y-%m")

    logger.info("=== 日次レポート開始: %s ===", today_str)

    # --- 1. データ取得 ---
    logger.info("Shopify: 昨日の注文取得")
    yesterday_orders = shopify_client.get_yesterday_orders()

    logger.info("Shopify: 月次累計注文取得")
    mtd_orders = shopify_client.get_month_to_date_orders()

    logger.info("Shopify: 30日注文取得（初速分析用）")
    orders_30d = shopify_client.get_orders_in_days(30)
    orders_14d = shopify_client.get_orders_in_days(14)
    orders_7d = shopify_client.get_orders_in_days(7)

    logger.info("Shopify: 在庫取得")
    shopify_stocks = shopify_client.get_inventory_by_sku()

    logger.info("OPENLOGI: 在庫取得")
    openlogi_stocks = openlogi_client.get_inventory()

    logger.info("Google Sheets: マスタデータ取得")
    adjustments = sheets_client.get_inventory_adjustments()
    product_master = sheets_client.get_product_master()
    sales_target = sheets_client.get_sales_target(year_month)

    # --- 2. KPI計算 ---
    yesterday_kpi = shopify_client.calc_sales_kpi(yesterday_orders)
    mtd_kpi = shopify_client.calc_sales_kpi(mtd_orders)

    # 前日比（2日前データと比較）
    two_days_ago_orders = shopify_client.get_orders(
        (yesterday - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0),
        (yesterday - timedelta(days=1)).replace(hour=23, minute=59, second=59),
    )
    two_days_ago_kpi = shopify_client.calc_sales_kpi(two_days_ago_orders)

    prev_revenue = two_days_ago_kpi["total_revenue"]
    yesterday_revenue = yesterday_kpi["total_revenue"]
    revenue_change_pct = (
        (yesterday_revenue - prev_revenue) / prev_revenue * 100
        if prev_revenue > 0 else 0.0
    )

    # 目標比
    target_pct = (
        mtd_kpi["total_revenue"] / sales_target * 100
        if sales_target > 0 else 0.0
    )

    # --- 3. SKU別集計 ---
    sku_sales_yesterday = shopify_client.calc_sku_sales(yesterday_orders)
    sku_sales_30d = shopify_client.calc_sku_sales(orders_30d)
    sku_sales_14d = shopify_client.calc_sku_sales(orders_14d)
    sku_sales_7d = shopify_client.calc_sku_sales(orders_7d)

    # TOP10
    top10_skus = sorted(sku_sales_30d.items(), key=lambda x: x[1], reverse=True)[:10]
    top10 = [
        {
            "sku": sku,
            "product_name": product_master.get(sku, {}).get("product_name", sku),
            "qty_30d": qty,
            "qty_14d": sku_sales_14d.get(sku, 0),
            "qty_7d": sku_sales_7d.get(sku, 0),
        }
        for sku, qty in top10_skus
    ]

    # カテゴリ別売上
    category_revenue: dict[str, int] = {}
    for order in mtd_orders:
        for item in order.get("line_items", []):
            sku = item.get("sku", "").strip()
            cat = product_master.get(sku, {}).get("category", "other")
            revenue = int(float(item.get("price", 0)) * int(item.get("quantity", 0)))
            category_revenue[cat] = category_revenue.get(cat, 0) + revenue

    # --- 4. 在庫計算 ---
    inventory_table = inv_module.build_inventory_table(
        openlogi_stocks, shopify_stocks, adjustments, product_master
    )
    alerts = inv_module.detect_alerts(inventory_table, sku_sales_30d)

    # --- 5. AIコメント生成 ---
    report_data = {
        "kpi": {
            "yesterday_revenue": yesterday_revenue,
            "order_count": yesterday_kpi["order_count"],
            "buyer_count": yesterday_kpi["buyer_count"],
            "avg_order_value": yesterday_kpi["avg_order_value"],
            "revenue_change_pct": revenue_change_pct,
            "mtd_revenue": mtd_kpi["total_revenue"],
            "target_pct": target_pct,
        },
        "top_skus": top10,
        "alerts": alerts,
    }
    comment = ai_comment.generate_daily_comment(report_data)

    # --- 6. HTMLレポート生成 ---
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("daily_report.html")

    html = template.render(
        report_date=yesterday_str,
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        # KPI
        yesterday_revenue=yesterday_revenue,
        revenue_change_pct=revenue_change_pct,
        order_count=yesterday_kpi["order_count"],
        buyer_count=yesterday_kpi["buyer_count"],
        avg_order_value=yesterday_kpi["avg_order_value"],
        mtd_revenue=mtd_kpi["total_revenue"],
        mtd_order_count=mtd_kpi["order_count"],
        sales_target=sales_target,
        target_pct=target_pct,
        # 商品分析
        top10=top10,
        category_revenue=sorted(category_revenue.items(), key=lambda x: x[1], reverse=True),
        # 在庫
        inventory_table=sorted(
            [i for i in inventory_table if i.openlogi_stock > 0 or i.shopify_stock > 0],
            key=lambda x: x.available_stock
        ),
        # アラート
        stockout_risk=alerts["stockout_risk"],
        stagnant=alerts["stagnant"][:10],
        large_diff=alerts["large_diff"][:10],
        # AIコメント
        ai_comment=comment,
    )

    # --- 7. メール送信 ---
    subject = f"【Venica】{yesterday_str} 日次経営レポート"
    gmail_client.send_html_email(subject, html)

    # --- 8. ログ記録 ---
    sheets_client.write_log("daily", "success")
    logger.info("=== 日次レポート完了 ===")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        logger.exception("日次レポート失敗: %s", e)
        try:
            sheets_client.write_log("daily", "error", str(e))
        except Exception:
            pass
        sys.exit(1)
