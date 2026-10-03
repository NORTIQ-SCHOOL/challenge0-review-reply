"""課題2の本体（ここを実装する）。仕様は CHALLENGE.md を見てください。"""

from __future__ import annotations

import json
import re

REPLY_MAX = 400       # 返信案（店名の行を含む）
SUMMARY_MAX = 60      # 口コミの要約
NOTIFY_MAX = 1000     # 店主へのLINE通知

PHONE_MASK = "［電話番号］"
EMAIL_MASK = "［メール］"

URGENT_WORDS = ("食中毒", "怪我", "けが", "ケガ", "異物", "返金", "訴え", "警察", "保健所", "弁護士")
PROMISE_WORDS = ("返金いたします", "返金します", "全額返金", "無料にいたします", "無料にします",
                 "補償いたします", "補償します", "賠償いたします", "賠償します")


def classify_urgency(review: dict) -> str:
    """"high"・"medium"・"low" のどれかを返す。"""
    raise NotImplementedError


def detect_injection(text: str) -> bool:
    """口コミの中に、AIへの指示らしき文があれば True。"""
    raise NotImplementedError


def draft_reply(review: dict, shop: dict, llm) -> dict:
    """口コミへの返信案と、店主に知らせるべきかの判定を返す。"""
    raise NotImplementedError


def format_line_notification(review: dict, result: dict) -> str:
    """店主に送るLINEの文面をつくる。"""
    raise NotImplementedError
