"""时间工具。集中在此，方便测试时替换。"""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """UTC ISO8601（秒精度）。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
