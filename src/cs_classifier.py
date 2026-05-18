"""
CS問い合わせ自動分類モジュール
"""
from __future__ import annotations
import re
from typing import NamedTuple

import sheets_client

DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "配送": ["届かない", "遅延", "追跡", "配達", "発送", "運送", "未着", "配送"],
    "サイズ": ["サイズ", "大きい", "小さい", "丈", "身幅", "着丈", "フィット", "寸法"],
    "返品交換": ["返品", "交換", "返却", "返送", "キャンセル"],
    "不良": ["不良", "傷", "汚れ", "破れ", "穴", "縫製", "ほつれ", "色落ち", "臭い"],
    "決済": ["支払", "決済", "クレジット", "エラー", "請求", "二重", "領収"],
    "その他": [],
}


class CsTicket(NamedTuple):
    ticket_id: str
    subject: str
    body: str
    date: str
    category: str = ""


def load_keywords() -> dict[str, list[str]]:
    """Google SheetsのCS_KEYWORDSシートからキーワードを読み込む。失敗時はデフォルト使用。"""
    try:
        kws = sheets_client.get_cs_keywords()
        return kws if kws else DEFAULT_KEYWORDS
    except Exception:
        return DEFAULT_KEYWORDS


def classify(text: str, keywords: dict[str, list[str]] | None = None) -> str:
    """テキストからCSカテゴリを判定する"""
    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    normalized = text.lower()

    for category, kw_list in keywords.items():
        if category == "その他":
            continue
        for kw in kw_list:
            if kw.lower() in normalized:
                return category

    return "その他"


def classify_tickets(tickets: list[CsTicket]) -> list[CsTicket]:
    """チケットリストを一括分類する"""
    keywords = load_keywords()
    result = []
    for t in tickets:
        combined = f"{t.subject} {t.body}"
        category = classify(combined, keywords)
        result.append(t._replace(category=category))
    return result


def aggregate(tickets: list[CsTicket]) -> dict[str, dict]:
    """
    カテゴリ別に集計して返す。
    戻り値: {カテゴリ名: {count, tickets}}
    """
    agg: dict[str, dict] = {}
    for t in tickets:
        cat = t.category or "その他"
        if cat not in agg:
            agg[cat] = {"count": 0, "tickets": []}
        agg[cat]["count"] += 1
        agg[cat]["tickets"].append(t)

    return dict(sorted(agg.items(), key=lambda x: x[1]["count"], reverse=True))
