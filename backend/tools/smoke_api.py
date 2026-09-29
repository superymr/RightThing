"""API 冒烟测试：对**真实运行中的服务**发 HTTP 请求，走完整链路。

    python -m app.cli serve --port 8010        # 另开一个终端
    python tools/smoke_api.py                  # 默认 http://127.0.0.1:8010

为什么不用 curl/PowerShell 手敲：中文 JSON 在 shell 里转义极易出错，
而且 SSE 需要流式读取。只用标准库，避免再引入 http 客户端依赖。

它覆盖 pytest 覆盖不到的东西：**真实的网络栈、真实的 uvicorn、真实的流式响应**。
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

DEFAULT_BASE = "http://127.0.0.1:8010"

PASS = "  [OK]  "
FAIL = "  [FAIL]"

_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"{PASS if condition else FAIL} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        _failures.append(name)


def _has_pii(text: str) -> bool:
    """复用被测代码自己的 PII 定义。

    刻意**不**在这里另写一套正则：那样两边的「什么算个人信息」会各自漂移，
    而这条检查的意义恰恰是「服务端用的就是我们认为的那套规则」。
    """
    # 本脚本位于 backend/tools/，直接 `python tools/smoke_api.py` 时
    # sys.path[0] 是 tools/ 而不是 backend/，所以要手动补上才能 import app.*
    import sys
    from pathlib import Path

    backend = str(Path(__file__).resolve().parent.parent)
    if backend not in sys.path:
        sys.path.insert(0, backend)

    from app.utils.sanitize import contains_pii

    return contains_pii(text)


def request(
    base: str, method: str, path: str, body: Any = None, *, timeout: float = 120.0
) -> tuple[int, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def read_sse(base: str, path: str, *, timeout: float = 180.0) -> list[dict]:
    """流式读取 SSE，返回解析后的事件列表。"""
    events: list[dict] = []
    req = urllib.request.Request(base + path, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip("\n")
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[len("data: ") :]))
                except json.JSONDecodeError:
                    pass
    return events


def main(argv: list[str]) -> int:
    base = (argv[1] if len(argv) > 1 else DEFAULT_BASE).rstrip("/")
    print(f"目标服务：{base}\n")

    # ---------- 元信息 ----------
    print("[元信息]")
    status, health = request(base, "GET", "/api/health")
    check(
        "GET /api/health 返回 200",
        status == 200,
        f"status={health.get('status') if health else '?'}",
    )
    check(
        "健康检查里没有泄露 API Key",
        "api_key" not in json.dumps(health, ensure_ascii=False).lower(),
    )

    status, directions = request(base, "GET", "/api/directions")
    check("GET /api/directions 列出方向", status == 200 and len(directions["directions"]) > 0)

    # ★ 这个脚本必须同时适配 mock 与真实模型两种后端。
    #
    # 早先这里硬编码了「样本量 == 24」「必须有『数据分析师』方向」—— 那些只在
    # mock 规则引擎下成立（它的方向推荐来自内置词表）。项目一旦接上真实模型，
    # 方向名与命中样本量都会变，冒烟测试就必然失败。
    # 一个**在项目自己的目标配置下必然失败**的测试比没有测试更糟：
    # 它会训练人忽略红灯。所以断言只保留与后端无关的不变量。
    provider = (health or {}).get("provider", "")
    is_mock = provider == "mock"
    print(f"  （后端：{provider or '未知'}{'，按 mock 的确定性子集断言' if is_mock else '，断言对方向名保持中立'}）")

    # ---------- 归一化 ----------
    print("\n[技能归一化]")
    status, normalized = request(
        base, "POST", "/api/skills/normalize", {"skills": "python3, 熟练使用ROS, 星际导航"}
    )
    check("POST /api/skills/normalize 接受字符串输入", status == 200)
    canon = {item["canonical"] for item in normalized["items"]}
    check("别名收敛正确", canon == {"Python", "ROS", "星际导航"}, f"得到 {sorted(canon)}")

    # ---------- 同步分析 ----------
    print("\n[同步分析]")
    body = {
        "skills": ["数据分析", "Python", "ROS", "C++"],
        "max_directions": 2,
        "limit_per_direction": 12,
        "sync": True,
    }
    status, task = request(base, "POST", "/api/analyze", body)
    check("POST /api/analyze (sync) 返回 200", status == 200)
    result = (task or {}).get("result") or {}
    session_id = result.get("session_id", 0)
    check("分析完成且产生 session_id", task.get("status") == "done" and session_id > 0)

    total_jobs = result.get("total_jobs", 0)
    if is_mock:
        # mock 的方向推荐是确定性的，两个方向都能在内置样例里拿满 12 条
        check("样本量符合预期", total_jobs == 24, f"{total_jobs} 条")
    else:
        # 真实模型会推荐样例数据未必覆盖的方向，样本量因此不固定。
        # 这里只断言「确实拿到了样本」——具体数字取决于模型推荐了什么。
        check("拿到了可分析的样本", total_jobs > 0, f"{total_jobs} 条")
    check(
        "每个方向都报告了采集量与成功量",
        all(d.get("total_jobs", 0) >= d.get("ok_jobs", 0) for d in result.get("directions", [])),
        f"{len(result.get('directions', []))} 个方向",
    )

    # ---------- 看板（从数据库读回） ----------
    print("\n[看板读回]")
    status, board = request(base, "GET", f"/api/sessions/{session_id}")
    check("GET /api/sessions/{id} 返回 200", status == 200)
    check("看板样本量与运行时一致", board.get("total_jobs") == result.get("total_jobs"))

    # 断言挂在「真正有样本的那个方向」上，而不是某个写死的方向名 ——
    # 后者只在 mock 下成立，真实模型推荐的方向名完全可能不同。
    active_direction = next(
        (d for d in board.get("directions", []) if d.get("ok_jobs", 0) > 0), None
    )
    check(
        "至少有一个方向拿到了可用样本",
        active_direction is not None,
        f"方向：{[d['title'] for d in board.get('directions', [])]}",
    )

    if active_direction:
        print(f"  （对「{active_direction['title']}」做深入断言，{active_direction['ok_jobs']} 条样本）")
        all_skills = (
            active_direction["languages"]
            + active_direction["hard_skills"]
            + active_direction["domain_knowledge"]
            + active_direction["soft_skills"]
        )
        check("抽出了技能且覆盖率在合理区间", bool(all_skills) and all(
            0.0 < s["coverage"] <= 1.0 for s in all_skills
        ), f"{len(all_skills)} 项技能")
        check("缺口分析有内容", active_direction["gap"]["coverage_score"] > 0)

        if is_mock:
            # 这条只有在 mock 路径下才有确定答案，单独 guard 住
            data_direction = next(
                (d for d in board["directions"] if d["title"] == "数据分析师"), None
            )
            check("找到「数据分析师」方向", data_direction is not None)
            if data_direction:
                top = {s["canonical"] for s in data_direction["languages"][:2]}
                check("编程语言排行 Top2 = SQL/Python", top == {"SQL", "Python"}, f"得到 {sorted(top)}")

        job_id = active_direction["jobs"][0]["job_id"]
        status, job = request(base, "GET", f"/api/jobs/{job_id}")
        check("GET /api/jobs/{id} 返回原文与结构化结果", status == 200 and bool(job["raw_text"]))
        skills = (
            job["profile"]["programming_languages"]
            + job["profile"]["hard_skills"]
            + job["profile"]["domain_knowledge"]
        )
        check(
            "每条技能都有原文依据（抗幻觉不变量）",
            all(s["evidence"] and s["evidence"] in job["raw_text"] for s in skills),
            f"{len(skills)} 项技能",
        )
        check(
            "JD 正文不含未脱敏的个人信息",
            not _has_pii(job["raw_text"]),
            "手机号/邮箱应立即在入库前被打码",
        )

    # ---------- 异步 + SSE ----------
    print("\n[异步任务与 SSE]")
    status, started = request(base, "POST", "/api/analyze", {**body, "sync": False})
    check("POST /api/analyze (async) 返回 202", status == 202)
    task_id = started.get("task_id", "")

    events = read_sse(base, f"/api/tasks/{task_id}/events")
    stages = [e.get("stage") for e in events]
    check("SSE 流包含完整阶段", {"normalize", "directions", "extract", "done"} <= set(stages))
    check("SSE 报告了逐条解析进度", any(e.get("total", 0) > 0 for e in events))
    check("SSE 流正常终止", bool(stages) and stages[-1] == "done")

    status, polled = request(base, "GET", f"/api/tasks/{task_id}")
    check("轮询与 SSE 结论一致", polled.get("status") == "done")
    async_session = (polled.get("result") or {}).get("session_id", 0)
    check(
        "异步任务是独立的一次分析（新建会话）",
        async_session > 0 and async_session != session_id,
        f"同步 session={session_id}，异步 session={async_session}",
    )

    # ---------- 手动录入 ----------
    print("\n[手动录入 JD]")
    jd = (
        "岗位名称：高级数据工程师\n"
        "岗位职责：\n"
        "1. 负责数据平台建设\n"
        "任职要求：\n"
        "1. 熟练掌握Python与SQL\n"
        "2. 熟悉Flink与Kafka\n"
    )
    status, manual = request(base, "POST", "/api/jobs/manual", {"text": jd})
    check("POST /api/jobs/manual 返回 201", status == 201)
    if status == 201:
        names = {
            s["name"]
            for s in (
                manual["job"]["profile"]["programming_languages"]
                + manual["job"]["profile"]["hard_skills"]
            )
        }
        check("抽出预期技能", {"Python", "SQL", "Flink", "Kafka"} <= names, f"得到 {sorted(names)}")

    # ---------- 错误契约 ----------
    print("\n[错误契约]")
    cases = [
        ("空输入", "POST", "/api/analyze", {}, 422, "empty_input"),
        (
            "参数越界",
            "POST",
            "/api/analyze",
            {"skills": ["x"], "max_directions": 99},
            422,
            "validation_error",
        ),
        ("会话不存在", "GET", "/api/sessions/99999", None, 404, "not_found"),
        ("岗位不存在", "GET", "/api/jobs/99999", None, 404, "not_found"),
        ("任务不存在", "GET", "/api/tasks/nope", None, 404, "not_found"),
    ]
    for name, method, path, payload, want_status, want_code in cases:
        status, resp = request(base, method, path, payload)
        code = ((resp or {}).get("error") or {}).get("code")
        check(
            f"{name} → {want_status}/{want_code}",
            status == want_status and code == want_code,
            f"实际 {status}/{code}",
        )

    # ---------- 结论 ----------
    print()
    if _failures:
        print(f"失败 {len(_failures)} 项：{'、'.join(_failures)}")
        return 1
    print("全部通过：HTTP 层、SSE 流、看板读回、错误契约均符合预期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
