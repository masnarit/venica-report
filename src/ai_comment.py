"""
Claude APIを使った経営コメント自動生成
"""
from __future__ import annotations
import logging
from typing import Any

import config

logger = logging.getLogger(__name__)


def generate_daily_comment(report_data: dict[str, Any]) -> str:
    """
    日次レポートデータを渡して経営者向けコメントを生成する。
    Claude APIキーが未設定の場合はデフォルトコメントを返す。
    """
    if not config.ANTHROPIC_API_KEY:
        return _fallback_comment(report_data)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

        kpi = report_data.get("kpi", {})
        alerts = report_data.get("alerts", {})
        top_skus = report_data.get("top_skus", [])

        prompt = f"""
あなたはD2Cアパレルブランド「Venica」の経営分析アシスタントです。
以下の昨日のデータを分析し、社長向けに簡潔な日本語コメント（3〜5点の箇条書き）を作成してください。

## 昨日の実績
- 売上: {kpi.get('yesterday_revenue', 0):,}円（前日比: {kpi.get('revenue_change_pct', 0):+.1f}%）
- 注文件数: {kpi.get('order_count', 0)}件
- 月次累計: {kpi.get('mtd_revenue', 0):,}円（目標比: {kpi.get('target_pct', 0):.1f}%）
- 平均注文単価: {kpi.get('avg_order_value', 0):,}円

## 売れ筋TOP3
{chr(10).join(f'- {s.get("product_name", s.get("sku", ""))}: {s.get("qty", 0)}点' for s in top_skus[:3])}

## アラート
- 欠品リスク: {len(alerts.get('stockout_risk', []))}件
- 在庫差異: {len(alerts.get('large_diff', []))}件
- 滞留在庫: {len(alerts.get('stagnant', []))}件

## コメント作成の注意点
- 数値の変化要因と見るべきポイントを具体的に
- アラートがある場合は優先して言及
- ポジティブな点・要注意点の両方をバランスよく
- 「・」始まりの箇条書き、各1行で簡潔に
"""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    except Exception as e:
        logger.warning("AIコメント生成失敗（フォールバック使用）: %s", e)
        return _fallback_comment(report_data)


def _fallback_comment(report_data: dict[str, Any]) -> str:
    """Claude API未設定時のシンプルコメント"""
    kpi = report_data.get("kpi", {})
    alerts = report_data.get("alerts", {})
    lines = []

    change = kpi.get("revenue_change_pct", 0)
    if change > 10:
        lines.append(f"・前日比 {change:+.1f}% と好調。要因分析を推奨します。")
    elif change < -10:
        lines.append(f"・前日比 {change:+.1f}% と低調。原因確認が必要です。")
    else:
        lines.append(f"・前日比 {change:+.1f}% で概ね横ばいです。")

    target_pct = kpi.get("target_pct", 0)
    if target_pct > 0:
        lines.append(f"・月次目標進捗: {target_pct:.1f}%")

    stockout = alerts.get("stockout_risk", [])
    if stockout:
        skus = "、".join(s.get("sku", "") for s in stockout[:3])
        lines.append(f"・欠品リスクあり: {skus}（追加発注を検討してください）")

    diff_alerts = alerts.get("large_diff", [])
    if diff_alerts:
        lines.append(f"・在庫差異 {len(diff_alerts)}件を検出。棚卸し確認を推奨します。")

    return "\n".join(lines) if lines else "・特筆すべき変化はありません。"
