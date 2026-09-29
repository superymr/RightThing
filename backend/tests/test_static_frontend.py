"""前端托管（`api/static.py`）的测试。

这一层很容易被当成「只是挂个静态目录」而跳过测试，但它有两个真实的坑：
1. **SPA fallback 不能吃掉 `/api/*`** —— 否则拼错的接口路径会返回 200 + HTML，
   前端会把它当成「接口返回了奇怪的东西」，把排查方向彻底带偏；
2. **目录穿越** —— `/../../etc/passwd` 这类请求不能让 static 层把 dist 之外的文件吐出来。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings


def _make_dist(tmp_path):
    """伪造一份构建产物。不需要真的跑一次 vite build 才能测托管逻辑。"""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")
    (dist / "favicon.ico").write_bytes(b"\x00\x01")
    return dist


def _client(tmp_path, dist) -> TestClient:
    settings = Settings(llm_provider="mock", db_path=tmp_path / "static.db")
    return TestClient(
        create_app(
            settings,
            configure_logging=False,
            serve_frontend=True,
            frontend_dist=dist,
        )
    )


class TestFrontendMounting:
    def test_root_serves_index(self, tmp_path):
        dist = _make_dist(tmp_path)
        with _client(tmp_path, dist) as client:
            response = client.get("/")
            assert response.status_code == 200
            assert "id=root" in response.text

    def test_spa_deep_link_falls_back_to_index(self, tmp_path):
        """刷新 /sessions/1 不能 404 —— 那个路径在磁盘上并不存在。"""
        dist = _make_dist(tmp_path)
        with _client(tmp_path, dist) as client:
            response = client.get("/sessions/1")
            assert response.status_code == 200
            assert "id=root" in response.text

    def test_real_asset_is_served(self, tmp_path):
        dist = _make_dist(tmp_path)
        with _client(tmp_path, dist) as client:
            response = client.get("/assets/app.js")
            assert response.status_code == 200
            assert "console.log" in response.text

    def test_unknown_api_path_returns_json_404(self, tmp_path):
        """关键回归：/api/* 必须走错误契约，而不是被 SPA fallback 兜成 HTML。"""
        dist = _make_dist(tmp_path)
        with _client(tmp_path, dist) as client:
            response = client.get("/api/does-not-exist")
            assert response.status_code == 404
            assert response.headers["content-type"].startswith("application/json")
            assert response.json()["error"]["code"] == "not_found"

    def test_api_still_works_when_frontend_mounted(self, tmp_path):
        dist = _make_dist(tmp_path)
        with _client(tmp_path, dist) as client:
            assert client.get("/api/health").json()["status"] == "ok"

    def test_directory_traversal_is_refused(self, tmp_path):
        dist = _make_dist(tmp_path)
        (tmp_path / "secret.txt").write_text("top-secret", encoding="utf-8")
        with _client(tmp_path, dist) as client:
            # TestClient/httpx 会规范化 ".."，所以用一个编码过的等价写法
            response = client.get("/%2e%2e/secret.txt")
            assert "top-secret" not in response.text

    def test_no_dist_keeps_json_root(self, tmp_path):
        """没构建前端时，根路径必须回落到 JSON 欢迎信息（M2 的行为不能回归）。"""
        settings = Settings(llm_provider="mock", db_path=tmp_path / "nodist.db")
        with TestClient(
            create_app(
                settings,
                configure_logging=False,
                serve_frontend=True,
                frontend_dist=tmp_path / "missing",
            )
        ) as client:
            body = client.get("/").json()
            assert body["docs"] == "/docs"
            assert "npm run build" in body["hint"]
