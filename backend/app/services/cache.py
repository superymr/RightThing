"""LLM 结果缓存。

**这不是性能优化，而是产品正确性的一部分。**

分析类产品必须可复现：同一个输入，今天和明天跑出来的排行榜应当一致。
如果把缓存当优化，团队就会倾向于「反正结果差不多」而容忍随机性；
把它当正确性约束，`temperature=0` + 缓存命中就是一条硬规则。

缓存键 = sha256(kind | prompt_version | model | payload)
=> 改 Prompt、换模型都会自然失效，不会出现「改了没用」的幽灵问题。
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from ..models.db import Database
from ..utils.timeutil import now_iso


def make_cache_key(*, kind: str, prompt_version: str, model: str, payload: str) -> str:
    digest = hashlib.sha256()
    for part in (kind, prompt_version, model, payload):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")  # 分隔符，避免拼接歧义
    return digest.hexdigest()


class LLMCache:
    def __init__(self, db: Database, *, enabled: bool = True) -> None:
        self.db = db
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        # 抽取阶段是多线程并发调用的，SQLite 写入需要串行化
        self._lock = threading.Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self._lock:
            row = self.db.query_one(
                "SELECT response_json FROM llm_cache WHERE cache_key = ?", (key,)
            )
            if row is None:
                self.misses += 1
                return None
            self.hits += 1
            self.db.execute(
                "UPDATE llm_cache SET hit_count = hit_count + 1 WHERE cache_key = ?", (key,)
            )
        try:
            return json.loads(row["response_json"])
        except json.JSONDecodeError:
            # 缓存损坏：当作未命中，让上层重新调用
            return None

    def put(
        self,
        key: str,
        *,
        kind: str,
        model: str,
        prompt_version: str,
        payload: dict[str, Any],
    ) -> None:
        if not self.enabled:
            return
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO llm_cache "
                "(cache_key, kind, model, prompt_version, response_json, created_at, hit_count) "
                "VALUES (?, ?, ?, ?, ?, ?, COALESCE("
                "  (SELECT hit_count FROM llm_cache WHERE cache_key = ?), 0))",
                (
                    key,
                    kind,
                    model,
                    prompt_version,
                    json.dumps(payload, ensure_ascii=False),
                    now_iso(),
                    key,
                ),
            )

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
