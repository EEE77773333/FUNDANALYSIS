"""
AI 分析引擎
===========
封装 LLM 调用，统一走 **OpenAI 兼容协议**，因此同一个后端即可驱动：

- 云端 API：DeepSeek / 通义千问 / 智谱 GLM / Kimi / OpenAI / 硅基流动 / OpenRouter …
- 本地推理：Ollama / vLLM / LM Studio（base_url 指向本机即可，零 API 成本）
- 原生协议：Anthropic Claude（单独后端）

配置来自 core/config.py（环境变量）与 core/user_integrations.py（用户自带密钥 BYOK），
优先级：会话覆盖 > 用户账户配置 > .env。

支持流式和非流式两种分析模式，自动处理 Token 统计和错误恢复。
"""

import logging
import time
from typing import Any, Dict, Generator, Optional

from .config import config

logger = logging.getLogger(__name__)

# ============================================================
# 类型
# ============================================================

AnalysisResult = Dict[str, Any]


# ============================================================
# OpenAI 兼容后端（覆盖绝大多数云端 API 与本地推理服务）
# ============================================================


class _OpenAICompatBackend:
    """
    通用 OpenAI 兼容后端。

    只要服务实现了 /chat/completions，就能用这里统一调用，
    差别仅在 base_url / api_key / model 三个参数。
    """

    def __init__(self, api_key: str, base_url: str, model: str):
        self._api_key = api_key or "not-needed"  # 本地推理服务通常不校验 key
        self._base_url = base_url or None
        self._model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            kwargs = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AnalysisResult:
        """非流式调用。"""
        start = time.time()
        try:
            resp = self.client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            elapsed = time.time() - start
            choice = resp.choices[0]
            content = choice.message.content or ""
            usage = resp.usage

            logger.info(
                f"[LLM] 分析完成 — 模型: {self._model}, "
                f"耗时: {elapsed:.1f}s, "
                f"Token: {getattr(usage, 'prompt_tokens', 0)}+{getattr(usage, 'completion_tokens', 0)}"
            )

            return {
                "success": True,
                "content": content,
                "model": self._model,
                "usage": {
                    "input_tokens": getattr(usage, "prompt_tokens", 0),
                    "output_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                },
                "elapsed_seconds": round(elapsed, 1),
                "error": None,
            }

        except Exception as e:
            elapsed = time.time() - start
            return _error_result(self._model, str(e), elapsed)

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        extra_context: Optional[str] = None,
    ) -> Generator[str, None, AnalysisResult]:
        """流式调用。"""
        start = time.time()
        full_prompt = user_prompt
        if extra_context:
            full_prompt += f"\n\n---\n## 附加参考数据\n{extra_context}"

        input_tokens = 0
        output_tokens = 0

        try:
            kwargs = dict(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            # 部分第三方兼容服务不认 stream_options，失败时降级重试
            try:
                stream = self.client.chat.completions.create(
                    **kwargs, stream_options={"include_usage": True}
                )
            except Exception:
                stream = self.client.chat.completions.create(**kwargs)

            for chunk in stream:
                # 处理 usage chunk（多数服务在最后一个 chunk 返回）
                if hasattr(chunk, "usage") and chunk.usage:
                    input_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                    output_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0
                    continue

                # 处理思考 / 内容 delta
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta:
                        # 推理模型（deepseek-reasoner / QwQ 等）思考阶段走 reasoning_content
                        reasoning = getattr(delta, "reasoning_content", None)
                        if reasoning:
                            yield {"reasoning": reasoning}
                        if delta.content:
                            yield delta.content

            elapsed = time.time() - start
            logger.info(
                f"[LLM] 流式分析完成 — 模型: {self._model}, "
                f"耗时: {elapsed:.1f}s, "
                f"Token: {input_tokens}+{output_tokens}"
            )

            return {
                "success": True,
                "content": "",
                "model": self._model,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
                "elapsed_seconds": round(elapsed, 1),
                "error": None,
            }

        except Exception as e:
            elapsed = time.time() - start
            return _error_result(self._model, str(e), elapsed)


# 向后兼容别名（旧代码可能引用此名字）
_DeepSeekBackend = _OpenAICompatBackend


# ============================================================
# Anthropic 后端（保留作为备用）
# ============================================================


class _AnthropicBackend:
    """Anthropic Claude API 后端。"""

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self._api_key)
        return self._client

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AnalysisResult:
        start = time.time()
        try:
            resp = self.client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            elapsed = time.time() - start
            text = "".join(
                block.text for block in resp.content if hasattr(block, "text")
            )
            return {
                "success": True,
                "content": text,
                "model": self._model,
                "usage": {
                    "input_tokens": resp.usage.input_tokens,
                    "output_tokens": resp.usage.output_tokens,
                    "total_tokens": resp.usage.input_tokens + resp.usage.output_tokens,
                },
                "elapsed_seconds": round(elapsed, 1),
                "error": None,
            }
        except Exception as e:
            elapsed = time.time() - start
            return _error_result(self._model, str(e), elapsed)

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        extra_context: Optional[str] = None,
    ) -> Generator[str, None, AnalysisResult]:
        start = time.time()
        full_prompt = user_prompt
        if extra_context:
            full_prompt += f"\n\n---\n## 附加参考数据\n{extra_context}"

        input_tokens = 0
        output_tokens = 0

        try:
            with self.client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": full_prompt}],
            ) as stream:
                for event in stream:
                    if event.type == "content_block_delta":
                        d = event.delta
                        # 思考 delta（启用 thinking 时）单独产出
                        if getattr(d, "type", "") == "thinking_delta":
                            think = getattr(d, "thinking", "")
                            if think:
                                yield {"reasoning": think}
                        else:
                            text = getattr(d, "text", None)
                            if text:
                                yield text
                    elif event.type == "message_stop":
                        if hasattr(event, "message") and hasattr(event.message, "usage"):
                            input_tokens = event.message.usage.input_tokens
                            output_tokens = event.message.usage.output_tokens

            elapsed = time.time() - start
            return {
                "success": True,
                "content": "",
                "model": self._model,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
                "elapsed_seconds": round(elapsed, 1),
                "error": None,
            }
        except Exception as e:
            elapsed = time.time() - start
            return _error_result(self._model, str(e), elapsed)


# ============================================================
# 通用工具
# ============================================================


def _error_result(model: str, message: str, elapsed: float) -> AnalysisResult:
    return {
        "success": False,
        "content": "",
        "model": model,
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "elapsed_seconds": round(elapsed, 1),
        "error": message[:300],
    }


def _meter(result: AnalysisResult, source: str = "") -> None:
    """
    记账。计量逻辑集中在 core/metering.py，此处只负责在调用成功后触发。

    放在这一层（而不是各业务页面）是刻意的：页面里的手动记账一定会漏，
    而配额体系漏一次就等于失效。
    """
    try:
        from .metering import note_ai_call
        note_ai_call(
            usage=result.get("usage") or {},
            model=result.get("model", "") or "",
            source=source,
        )
    except Exception:
        logger.debug("用量记账失败（不影响分析结果）", exc_info=True)


# ============================================================
# AIAnalyzer 主类（多后端统一接口）
# ============================================================


class AIAnalyzer:
    """
    多后端 AI 分析引擎。

    后端选择依据生效的 LLM 配置（`config.effective_llm`）：
    - protocol == "openai"     → 通用 OpenAI 兼容后端（DeepSeek / 通义 / Ollama / vLLM …）
    - protocol == "anthropic"  → Anthropic Claude 原生后端

    使用示例:
        analyzer = AIAnalyzer()

        # 流式分析（推荐）
        stream = analyzer.analyze_stream(system_prompt, user_prompt)
        for chunk in stream:
            print(chunk, end="")

        # 非流式分析
        result = analyzer.analyze(system_prompt, user_prompt)
        print(result["content"])
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        default_max_tokens: int = 4096,
        default_temperature: float = 0.3,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        protocol: Optional[str] = None,
        preset: Optional[str] = None,
    ):
        """
        Args:
            provider: 兼容旧接口，"deepseek"→openai 协议，"anthropic"→anthropic 协议；None 则按生效配置
            model: 模型名，None 则按生效配置
            base_url / api_key / protocol / preset: 显式覆盖项（通常由 BYOK 配置解析提供）
        """
        self._provider = provider
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._protocol = protocol
        self._preset = preset
        self._default_max_tokens = default_max_tokens
        self._default_temperature = default_temperature
        self._backend = None

    def _resolve(self):
        """把显式覆盖项与生效配置合并成最终三元组。"""
        eff = config.effective_llm

        protocol = self._protocol or eff.protocol
        if self._provider:  # 旧接口兼容
            protocol = "anthropic" if self._provider == "anthropic" else "openai"

        return {
            "protocol": protocol or "openai",
            "base_url": self._base_url or eff.base_url,
            "api_key": self._api_key or eff.api_key,
            "model": self._model or eff.model,
            "preset": self._preset or eff.preset,
        }

    def _get_backend(self):
        """延迟初始化后端。"""
        if self._backend is not None:
            return self._backend

        r = self._resolve()
        protocol = r["protocol"]

        if protocol == "anthropic":
            if not r["api_key"]:
                raise ValueError(
                    "Anthropic API Key 未配置。请在「账户设置 → AI 模型」填写，"
                    "或在 .env 中设置 LLM_API_KEY。"
                )
            self._backend = _AnthropicBackend(
                api_key=r["api_key"],
                model=r["model"],
            )
        else:
            # OpenAI 兼容路径：本地推理服务允许空 key
            from .llm_presets import get_preset
            preset_obj = get_preset(r["preset"])
            needs_key = preset_obj.requires_key if preset_obj else True
            if needs_key and not r["api_key"]:
                raise ValueError(
                    "LLM API Key 未配置。请在「账户设置 → AI 模型」填写自己的密钥，"
                    "或在 .env 中设置 LLM_API_KEY（本地 Ollama 等无需密钥）。"
                )
            if not r["base_url"]:
                raise ValueError(
                    f"LLM 端点地址（base_url）为空。当前预设：{r['preset']}，"
                    "请在「账户设置 → AI 模型」补全。"
                )
            self._backend = _OpenAICompatBackend(
                api_key=r["api_key"],
                base_url=r["base_url"],
                model=r["model"],
            )

        return self._backend

    @property
    def is_ready(self) -> bool:
        """检查生效配置是否可用。"""
        return config.is_configured

    @property
    def model(self) -> str:
        return self._resolve()["model"]

    @model.setter
    def model(self, value: str):
        self._model = value
        self._backend = None  # 重置后端以使用新模型

    @property
    def provider(self) -> str:
        """兼容旧接口：按协议映射回旧语义。"""
        return "anthropic" if self._resolve()["protocol"] == "anthropic" else "deepseek"

    @provider.setter
    def provider(self, value: str):
        """兼容旧接口：切换提供商，自动重建后端。"""
        if value not in ("deepseek", "anthropic", "openai_compatible"):
            raise ValueError(f"不支持的提供商: {value}")
        self._provider = value
        self._backend = None  # 重建后端

    @property
    def preset(self) -> str:
        return self._resolve()["preset"]

    @property
    def base_url(self) -> str:
        return self._resolve()["base_url"]

    def switch_model(self, provider: str = None, model: str = None):
        """
        切换提供商和/或模型，自动重建后端。

        Args:
            provider: 提供商名称（兼容旧值 deepseek / anthropic），None 则保持不变
            model: 模型名称，None 则保持当前模型
        """
        if provider is not None:
            if provider not in ("deepseek", "anthropic", "openai_compatible"):
                raise ValueError(f"不支持的提供商: {provider}")
            self._provider = provider
        if model is not None:
            self._model = model
        self._backend = None  # 强制重建后端

    # ---- 非流式分析 ----

    def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        meter_source: str = "",
    ) -> AnalysisResult:
        """
        非流式 AI 分析。

        Args:
            meter_source: 调用来源标签（如 "famas" / "screen"），仅用于用量归因
        """
        backend = self._get_backend()
        result = backend.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens or self._default_max_tokens,
            temperature=temperature or self._default_temperature,
        )
        if result.get("success"):
            _meter(result, meter_source)
        return result

    # ---- 流式分析 ----

    def analyze_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra_context: Optional[str] = None,
        meter_source: str = "",
    ) -> Generator[str, None, AnalysisResult]:
        """
        流式 AI 分析。

        在生成器收尾处记账 —— 流式调用同样每次只计一次，
        且只在真正成功时计入，失败不扣用户额度。

        Yields:
            str: 增量文本块
        Returns:
            AnalysisResult: 最终结果（含 Token 统计）
        """
        backend = self._get_backend()
        inner = backend.chat_stream(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens or self._default_max_tokens,
            temperature=temperature or self._default_temperature,
            extra_context=extra_context,
        )

        def _metered():
            final = None
            while True:
                try:
                    chunk = next(inner)
                except StopIteration as e:
                    final = e.value
                    break
                yield chunk
            if final and final.get("success"):
                _meter(final, meter_source)
            return final

        return _metered()

    # ---- 辅助 ----

    def quick_chat(self, prompt: str, max_tokens: int = 1024) -> str:
        """快捷问答。"""
        result = self.analyze(
            system_prompt="你是一个专业、客观的金融分析助手。",
            user_prompt=prompt,
            max_tokens=max_tokens,
        )
        return result["content"] if result["success"] else f"错误: {result['error']}"

    def count_tokens_estimate(self, text: str) -> int:
        """粗略估算 Token 数。"""
        chinese = sum(1 for c in text if "一" <= c <= "鿿")
        others = len(text) - chinese
        return int(chinese / 1.5 + others / 4)


# ============================================================
# 全局单例
# ============================================================

_analyzer_instance: Optional[AIAnalyzer] = None
_analyzer_fingerprint: str = ""


def _config_fingerprint() -> str:
    """
    生成生效 LLM 配置的指纹。
    用户改了模型 / 换了自带密钥后，指纹变化即触发重建，避免沿用旧客户端。
    """
    try:
        eff = config.effective_llm
        import hashlib as _h
        key_digest = _h.sha256((eff.api_key or "").encode()).hexdigest()[:8]
        return f"{eff.protocol}|{eff.preset}|{eff.base_url}|{eff.model}|{key_digest}"
    except Exception:
        return ""


def get_analyzer() -> AIAnalyzer:
    """
    获取 AIAnalyzer 实例。

    - Streamlit 运行时：每个用户 session 独立实例，避免并发时跨会话串模型/Provider；
      并在生效配置发生变化（换模型 / 改 BYOK 密钥）时自动重建。
    - 非 Streamlit（如 FastAPI/脚本）：进程级单例，同样按配置指纹重建。
    """
    fp = _config_fingerprint()

    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:
            import streamlit as st
            inst = st.session_state.get("_ai_analyzer")
            if inst is None or st.session_state.get("_ai_analyzer_fp") != fp:
                inst = AIAnalyzer()
                st.session_state["_ai_analyzer"] = inst
                st.session_state["_ai_analyzer_fp"] = fp
            return inst
    except Exception:
        pass

    global _analyzer_instance, _analyzer_fingerprint
    if _analyzer_instance is None or _analyzer_fingerprint != fp:
        _analyzer_instance = AIAnalyzer()
        _analyzer_fingerprint = fp
    return _analyzer_instance
