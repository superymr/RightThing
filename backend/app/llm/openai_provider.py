"""OpenAI 兼容 Provider。

用标准库 urllib 实现，不依赖 openai / httpx —— 兼容 DeepSeek / Kimi / 通义 /
OpenAI / vLLM / Ollama 等任何实现了 /chat/completions 协议的端点。

换模型只改 .env，不改代码。
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from typing import Any

from ..config import Settings
from .base import LLMError, LLMResponse


def _strip_code_fence(text: str) -> str:
    """有些模型即使被要求「只输出 JSON」也会套一层 ```json 围栏。"""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_object(text: str) -> dict[str, Any]:
    """稳健地从模型输出中取出 JSON 对象。

    依次尝试：直接解析 → 去代码围栏 → 截取第一个 { 到最后一个 }。
    """
    candidates: list[str] = [text, _strip_code_fence(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    last_error: Exception | None = None
    for candidate in candidates:
        if not candidate.strip():
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
        last_error = ValueError(f"期望 JSON 对象，实际得到 {type(parsed).__name__}")
    raise LLMError(f"模型返回的内容无法解析为 JSON：{last_error}") from last_error


def _response_content(raw: dict[str, Any]) -> str:
    """读取兼容端点的文本结果，并把响应结构问题统一成 LLMError。"""
    try:
        return raw["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(
            f"响应结构异常，缺少 choices[0].message.content：{str(raw)[:300]}"
        ) from exc


class OpenAICompatibleProvider:
    """通过 HTTP 调用任意 OpenAI 兼容端点。"""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not settings.llm_api_key:
            raise LLMError(
                "未配置 LLM_API_KEY。请在 .env 中填写，或先用 LLM_PROVIDER=mock 跑通链路。"
            )
        self.endpoint = f"{settings.llm_base_url}/chat/completions"
        self.model = settings.extraction_model
        self.model_name = self.model

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # 抽取任务必须确定性，否则同一份 JD 两次结果不同，分析结论不可复现
            "temperature": self.settings.llm_temperature,
            "stream": False,
        }
        # 官方 DeepSeek 默认启用高强度思考。结构化JD抽取优先非思考模式。
        # 仅对官方端点发送厂商参数，避免破坏其他OpenAI兼容服务。
        if urlsplit(self.settings.llm_base_url).hostname == "api.deepseek.com":
            body["thinking"] = {"type": "enabled" if self.settings.llm_deepseek_thinking else "disabled"}
        # 优先请求结构化输出；不支持该参数的端点会自动降级（见下方重试逻辑）
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_object",
                "schema_name": schema_name,
            }
            body["_schema_hint"] = json_schema  # 仅注释用途，发送前会被移除

        payload = {k: v for k, v in body.items() if not k.startswith("_")}

        # HTTP 成功并不代表结构化输出成功。部分兼容模型偶尔会漏掉逗号、引号或
        # 右括号；这类瞬时格式错误应该让模型自行重写，而不是让整条分析任务失败。
        # 这里复用同一个重试配置，并保留原始上下文和错误输出供模型纠正。
        parse_attempts = max(1, self.settings.llm_max_retries + 1)
        token_in = 0
        token_out = 0
        last_error: LLMError | None = None

        for parse_attempt in range(parse_attempts):
            raw = self._post_with_retry(payload)
            usage = raw.get("usage") or {}
            token_in += int(usage.get("prompt_tokens") or 0)
            token_out += int(usage.get("completion_tokens") or 0)

            try:
                content = _response_content(raw)
                data = _extract_json_object(content)
            except LLMError as exc:
                last_error = exc
                if parse_attempt >= parse_attempts - 1:
                    break

                malformed = ""
                try:
                    malformed = _response_content(raw)
                except LLMError:
                    pass
                payload = {
                    **payload,
                    "messages": [
                        *body["messages"],
                        {"role": "assistant", "content": malformed[:8000]},
                        {
                            "role": "user",
                            "content": (
                                "上一条回答不是合法、完整的 JSON 对象，解析失败："
                                f"{exc}。请重新生成完整结果，严格只输出合法 JSON；"
                                "所有字符串中的双引号和换行必须正确转义，不要使用 Markdown 代码围栏。"
                            ),
                        },
                    ],
                }
                continue

            return LLMResponse(
                data=data,
                model=raw.get("model", self.model),
                token_in=token_in,
                token_out=token_out,
                raw_text=content,
                meta={
                    "provider": self.name,
                    "schema_name": schema_name,
                    "json_retries": parse_attempt,
                },
            )

        raise LLMError(
            f"模型连续 {parse_attempts} 次返回无效 JSON：{last_error}"
        ) from last_error

    # ------------------------------------------------------------------
    # 自检辅助（供 `jobradar doctor` 使用）
    # ------------------------------------------------------------------
    def list_models(self) -> list[str]:
        """列出端点支持的模型名。

        很多 OpenAI 兼容端点实现了 /models。这是排查「模型名写错」最快的手段 ——
        这类错误的表现往往只是一句含糊的 400，而这里能直接给出可选项。
        端点未实现 /models 时抛 LLMError，由调用方降级处理。
        """
        request = urllib.request.Request(
            f"{self.settings.llm_base_url}/models",
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(30.0, self.settings.llm_timeout)) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMError(f"GET /models 返回 HTTP {exc.code}") from exc
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            raise LLMError(f"无法连接 {self.settings.llm_base_url}：{exc}") from exc

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise LLMError("/models 响应结构不符合预期")
        return [str(item.get("id", "")) for item in data if isinstance(item, dict)]

    def check_connectivity(self) -> str:
        """一次最小化的真实调用，验证鉴权、配额与模型名。成功返回模型名。"""
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "只回复两个字：正常"}],
            "temperature": 0,
            "max_tokens": 16,
        }
        raw = self._post(payload)
        choices = raw.get("choices") or []
        if not choices:
            raise LLMError(f"响应中没有 choices：{str(raw)[:200]}")
        return str(raw.get("model", self.model))

    # ------------------------------------------------------------------
    def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        """指数退避重试。

        - 网络类错误 / 5xx / 429 → 重试；
        - 端点不认识 response_format → 摘掉该字段重试一次（降级兼容）；
        - 4xx（除 429）→ 直接放弃，重试没有意义。
        """
        attempts = max(1, self.settings.llm_max_retries + 1)
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                return self._post(payload)
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:300]
                except Exception:  # noqa: BLE001 - 读错误响应体失败不应影响主流程
                    pass

                if exc.code == 400 and "response_format" in payload:
                    payload = {k: v for k, v in payload.items() if k != "response_format"}
                    last_error = LLMError(f"端点不支持 response_format，已降级重试：{detail}")
                    continue
                if exc.code in (429, 500, 502, 503, 504):
                    last_error = LLMError(f"HTTP {exc.code}：{detail}")
                else:
                    raise LLMError(f"HTTP {exc.code}（不重试）：{detail}") from exc
            except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
                last_error = LLMError(f"网络错误：{exc}")
            except json.JSONDecodeError as exc:
                last_error = LLMError(f"响应不是合法 JSON：{exc}")

            if attempt < attempts - 1:
                time.sleep(min(2 ** attempt, 8))

        raise LLMError(f"LLM 调用在 {attempts} 次尝试后仍失败：{last_error}") from last_error

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.settings.llm_timeout) as response:
            return json.loads(response.read().decode("utf-8"))
