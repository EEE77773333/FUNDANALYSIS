"""
多模型路由
==========
在同一个 LLM 端点内做模型分级路由与自动降级，并追踪用量。

设计要点（与"BYOK / 自部署"模式对齐）：
    **降级只在同一端点内进行**。因为用 A 厂商的密钥无法调用 B 厂商的模型，
    跨端点降级是伪命题。所以候选模型 = 当前生效预设下的一组模型，共用同一组
    base_url + api_key。

    生效配置从哪里来：core/user_integrations.py（会话 > 用户账户 > .env）。

路由策略:
    1. 用户显式指定的模型最先尝试
    2. 其次是生效配置里的模型
    3. 再次是该预设下的其他常用模型（同端点，仅换模型名）
    4. 失败模型触发断路器，指数退避后自动恢复
    5. 记录每次调用的成功/失败与延迟，估算成本（成本表为参考值）

使用方式:
    from core.model_router import get_model_router

    router = get_model_router()
    result = router.chat(system_prompt, user_prompt, task_type="analysis")
"""

import time
import threading
from typing import Optional, Dict, List, Any, Generator
from dataclasses import dataclass, field
from collections import defaultdict

from .ai_analyzer import get_analyzer, AIAnalyzer, AnalysisResult
from .config import config
from .llm_presets import get_preset


# ============================================================
# 模型注册表
# ============================================================

@dataclass
class ModelEntry:
    """单个模型的注册信息"""
    name: str
    provider: str                        # "openai" | "anthropic"
    priority: int                        # 越小越优先
    max_tokens: int = 4096
    capabilities: List[str] = field(default_factory=list)  # ["analysis","chat","extract","stream"]
    cost_per_1k_input: float = 0.0       # 每千 token 输入成本（USD，参考值）
    cost_per_1k_output: float = 0.0      # 每千 token 输出成本（USD，参考值）
    avg_latency_ms: float = 0.0          # 平均延迟（动态更新）
    enabled: bool = True


# 默认模型注册表（内置参考收录）
#
# 注意：这里只是「已知模型的参考信息」，**不是**可用模型的唯一来源。
# 实际可用模型由生效的 LLM 预设决定（见 build_registry_from_presets）。
# 成本为公开报价的参考值，仅用于用量估算展示，不作为计费依据。
MODEL_REGISTRY: Dict[str, ModelEntry] = {
    # ---- DeepSeek ----
    "deepseek-chat": ModelEntry(
        name="deepseek-chat", provider="openai", priority=1, max_tokens=8192,
        capabilities=["analysis", "chat", "extract", "stream"],
        cost_per_1k_input=0.14, cost_per_1k_output=0.28,
    ),
    "deepseek-reasoner": ModelEntry(
        name="deepseek-reasoner", provider="openai", priority=2, max_tokens=16384,
        capabilities=["analysis", "chat", "extract", "stream", "deep_reasoning"],
        cost_per_1k_input=0.55, cost_per_1k_output=2.19,
    ),
    # ---- 通义千问 ----
    "qwen-max": ModelEntry(
        name="qwen-max", provider="openai", priority=3, max_tokens=8192,
        capabilities=["analysis", "chat", "stream"],
        cost_per_1k_input=0.34, cost_per_1k_output=1.37,
    ),
    "qwen-plus": ModelEntry(
        name="qwen-plus", provider="openai", priority=4, max_tokens=8192,
        capabilities=["analysis", "chat", "extract", "stream"],
        cost_per_1k_input=0.11, cost_per_1k_output=0.28,
    ),
    "qwen-turbo": ModelEntry(
        name="qwen-turbo", provider="openai", priority=10, max_tokens=8192,
        capabilities=["chat", "extract", "stream"],
        cost_per_1k_input=0.04, cost_per_1k_output=0.08,
    ),
    # ---- 智谱 GLM ----
    "glm-4-plus": ModelEntry(
        name="glm-4-plus", provider="openai", priority=3, max_tokens=8192,
        capabilities=["analysis", "chat", "stream"],
        cost_per_1k_input=0.07, cost_per_1k_output=0.07,
    ),
    "glm-4-flash": ModelEntry(
        name="glm-4-flash", provider="openai", priority=12, max_tokens=8192,
        capabilities=["chat", "extract", "stream"],
        cost_per_1k_input=0.0, cost_per_1k_output=0.0,
    ),
    # ---- Kimi ----
    "moonshot-v1-128k": ModelEntry(
        name="moonshot-v1-128k", provider="openai", priority=5, max_tokens=16384,
        capabilities=["analysis", "chat", "stream"],
        cost_per_1k_input=0.84, cost_per_1k_output=0.84,
    ),
    # ---- OpenAI ----
    "gpt-4o": ModelEntry(
        name="gpt-4o", provider="openai", priority=3, max_tokens=16384,
        capabilities=["analysis", "chat", "extract", "stream", "deep_reasoning"],
        cost_per_1k_input=2.50, cost_per_1k_output=10.00,
    ),
    "gpt-4o-mini": ModelEntry(
        name="gpt-4o-mini", provider="openai", priority=8, max_tokens=16384,
        capabilities=["analysis", "chat", "extract", "stream"],
        cost_per_1k_input=0.15, cost_per_1k_output=0.60,
    ),
    # ---- Anthropic（原生协议）----
    "claude-sonnet-4-6": ModelEntry(
        name="claude-sonnet-4-6", provider="anthropic", priority=3, max_tokens=8192,
        capabilities=["analysis", "chat", "extract", "stream"],
        cost_per_1k_input=3.00, cost_per_1k_output=15.00,
    ),
    "claude-opus-4-8": ModelEntry(
        name="claude-opus-4-8", provider="anthropic", priority=2, max_tokens=16384,
        capabilities=["analysis", "chat", "extract", "stream", "deep_reasoning"],
        cost_per_1k_input=15.00, cost_per_1k_output=75.00,
    ),
    "claude-haiku-4-5": ModelEntry(
        name="claude-haiku-4-5", provider="anthropic", priority=12, max_tokens=4096,
        capabilities=["chat", "extract"],
        cost_per_1k_input=0.80, cost_per_1k_output=4.00,
    ),
}


# 本地模型提示（用于成本展示）
LOCAL_MODEL_HINTS = ("qwen", "llama", "deepseek-r1", "mistral", "gemma", "phi")


def _is_local_model(name: str) -> bool:
    n = (name or "").lower()
    return any(h in n for h in LOCAL_MODEL_HINTS) and ":" in n


def build_registry() -> Dict[str, ModelEntry]:
    """
    依据生效的 LLM 预设构建注册表。

    - 先把内置参考表拷进来（保证成本/最大 token 等信息可用）
    - 再把当前预设声明的模型补进去（若是自定义模型，则以本地零成本记账）
    """
    registry: Dict[str, ModelEntry] = {k: ModelEntry(**vars(v)) for k, v in MODEL_REGISTRY.items()}

    eff = config.effective_llm
    preset = get_preset(eff.preset)
    protocol = eff.protocol or "openai"

    names: List[str] = []
    if eff.model:
        names.append(eff.model)
    if preset:
        names.extend(m for m in preset.models if m not in names)

    for idx, name in enumerate(names):
        if name in registry:
            # 已知模型：按当前协议更正 provider
            registry[name].provider = protocol
            continue
        registry[name] = ModelEntry(
            name=name,
            provider=protocol,
            priority=1 if idx == 0 else 5 + idx,
            max_tokens=8192,
            capabilities=["analysis", "chat", "extract", "stream"],
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
        )
    return registry


# 任务类型 → 模型能力需求（用于挑同端点内的合适模型，而非写死模型名）
TASK_TAG_PREFERENCE = {
    "analysis": ["analysis", "stream", "chat"],
    "deep_analysis": ["deep_reasoning", "analysis", "stream"],
    "chat": ["chat", "stream"],
    "extract": ["extract", "chat"],
    "quick": ["chat", "extract"],
    "stream": ["stream", "analysis", "chat"],
}


# ============================================================
# 用量追踪
# ============================================================

@dataclass
class UsageStats:
    """单模型用量统计"""
    total_calls: int = 0
    success_calls: int = 0
    fail_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: float = 0.0


# ============================================================
# 模型路由器
# ============================================================

class ModelRouter:
    """
    同端点多模型路由器。

    功能:
        - 按优先级路由，同端点内失败自动降级
        - 按任务类型选择合适模型
        - 用量统计和成本估算
        - 模型健康状态追踪（断路器）
    """

    def __init__(self):
        self._registry: Dict[str, ModelEntry] = build_registry()
        self._usage: Dict[str, UsageStats] = defaultdict(UsageStats)
        self._lock = threading.Lock()
        self._consecutive_failures: Dict[str, int] = defaultdict(int)
        self._circuit_breakers: Dict[str, float] = {}  # 模型名 -> 恢复时间戳
        self._endpoint_fingerprint = self._fingerprint()

    # ---- 配置变化感知 ----

    @staticmethod
    def _fingerprint() -> str:
        eff = config.effective_llm
        return f"{eff.protocol}|{eff.preset}|{eff.base_url}"

    def _refresh_if_stale(self):
        """端点或预设变化时重建注册表（BYOK 切换后立即生效）。"""
        fp = self._fingerprint()
        if fp != self._endpoint_fingerprint:
            with self._lock:
                self._registry = build_registry()
                self._endpoint_fingerprint = fp
                self._circuit_breakers.clear()
                self._consecutive_failures.clear()

    # ---- 注册管理 ----

    def get_models(self, enabled_only: bool = True) -> List[ModelEntry]:
        """获取所有已注册模型"""
        self._refresh_if_stale()
        models = list(self._registry.values())
        if enabled_only:
            models = [m for m in models if m.enabled]
        return sorted(models, key=lambda m: m.priority)

    def get_model(self, name: str) -> Optional[ModelEntry]:
        """获取单个模型信息"""
        self._refresh_if_stale()
        return self._registry.get(name)

    def enable_model(self, name: str, enabled: bool = True):
        """启用/禁用模型"""
        if name in self._registry:
            self._registry[name].enabled = enabled

    # ---- 路由 ----

    def _get_candidates(self, task_type: str = "analysis", preferred_model: str = None) -> List[str]:
        """
        获取候选模型列表（同端点内，按优先级排序）。

        降级只换模型名、不换端点 —— 用 A 厂商的 key 调 B 厂商的模型只会得到 404。

        候选范围：
        - 预设已声明模型列表（如 ollama / deepseek / qwen）→ **严格限定在该列表内**，
          避免把 registry 里其他厂商的模型混进来做无意义的降级。
        - 预设为 custom 或未声明模型 → 退回 registry 按能力标签挑选。
        """
        self._refresh_if_stale()
        eff = config.effective_llm
        preset = get_preset(eff.preset)
        this_protocol = eff.protocol or "openai"

        candidates: List[str] = []
        for m in (preferred_model, eff.model):
            if m and m not in candidates:
                candidates.append(m)

        preset_models = list(preset.models) if preset else []

        if preset_models:
            # 预设明确声明了模型：只在这个集合内降级
            for m in preset_models:
                if m not in candidates:
                    candidates.append(m)
            # 预设声明的模型都不可用时，允许同协议的 registry 模型兜底（仅自定义端点场景）
            if preset and preset.key not in ("custom",):
                return candidates

        # custom / 未声明模型的预设：按任务能力标签从 registry 挑选同协议模型
        for m in (preset_models or []):
            if m not in candidates:
                candidates.append(m)

        wanted = TASK_TAG_PREFERENCE.get(task_type, [])
        for entry in sorted(self._registry.values(), key=lambda x: x.priority):
            if entry.name in candidates or not entry.enabled:
                continue
            if entry.provider != this_protocol:
                continue  # 跨协议不降级
            if not wanted or any(c in entry.capabilities for c in wanted):
                candidates.append(entry.name)

        return candidates

    def _is_circuit_open(self, model_name: str) -> bool:
        """检查断路器是否打开（模型是否被暂时禁用）"""
        if model_name not in self._circuit_breakers:
            return False
        if time.time() >= self._circuit_breakers[model_name]:
            del self._circuit_breakers[model_name]
            self._consecutive_failures[model_name] = 0
            return False
        return True

    def _open_circuit(self, model_name: str):
        """打开断路器，暂时禁用模型"""
        self._consecutive_failures[model_name] += 1
        if self._consecutive_failures[model_name] >= 3:
            # 指数退避: 10s, 30s, 60s
            delay = 10 * (3 ** min(self._consecutive_failures[model_name] - 3, 2))
            self._circuit_breakers[model_name] = time.time() + delay

    def _record_usage(self, model_name: str, success: bool, input_tokens: int = 0,
                      output_tokens: int = 0, latency_ms: float = 0):
        """记录用量"""
        with self._lock:
            stats = self._usage[model_name]
            stats.total_calls += 1
            if success:
                stats.success_calls += 1
                stats.total_input_tokens += input_tokens
                stats.total_output_tokens += output_tokens
                stats.total_latency_ms += latency_ms
                self._consecutive_failures[model_name] = 0
            else:
                stats.fail_calls += 1
                self._open_circuit(model_name)

    def _apply_model(self, analyzer: AIAnalyzer, model_name: str):
        """
        只切换模型名，端点（base_url / api_key / 协议）保持生效配置不变。
        """
        analyzer.switch_model(model=model_name)

    # ---- 核心调用 ----

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        task_type: str = "analysis",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        preferred_model: str = None,
    ) -> AnalysisResult:
        """
        路由到模型执行 chat。

        按优先级尝试模型，直到成功或所有候选失败。
        """
        candidates = self._get_candidates(task_type, preferred_model)

        last_error = None
        for model_name in candidates:
            if self._is_circuit_open(model_name):
                continue

            entry = self._registry.get(model_name)
            max_tok = min(max_tokens, entry.max_tokens) if entry else max_tokens

            try:
                analyzer = get_analyzer()
                self._apply_model(analyzer, model_name)

                start = time.time()
                result = analyzer.analyze(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tok,
                    temperature=temperature,
                )
                latency = (time.time() - start) * 1000

                usage = result.get("usage", {})
                self._record_usage(
                    model_name, result.get("success", False),
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    latency_ms=latency,
                )

                if result.get("success"):
                    result["routed_model"] = model_name
                    return result
                last_error = result.get("error")

            except Exception as e:
                last_error = str(e)
                self._record_usage(model_name, False)

        return {
            "success": False,
            "content": "",
            "model": candidates[0] if candidates else "unknown",
            "usage": {},
            "elapsed_seconds": 0,
            "error": f"所有候选模型均失败。最后错误: {last_error}",
        }

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        task_type: str = "stream",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        preferred_model: str = None,
    ) -> Generator[str, None, AnalysisResult]:
        """
        路由到模型执行流式 chat。
        """
        candidates = self._get_candidates(task_type, preferred_model)

        last_error = None
        for model_name in candidates:
            if self._is_circuit_open(model_name):
                continue

            entry = self._registry.get(model_name)
            max_tok = min(max_tokens, entry.max_tokens) if entry else max_tokens

            try:
                analyzer = get_analyzer()
                self._apply_model(analyzer, model_name)

                start = time.time()
                stream = analyzer.analyze_stream(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tok,
                    temperature=temperature,
                )
                # 消费 stream，透传 chunk 并捕获 StopIteration 返回值
                full_content = ""
                final_result = None
                while True:
                    try:
                        chunk = next(stream)
                    except StopIteration as e:
                        final_result = e.value
                        break
                    full_content += chunk if isinstance(chunk, str) else ""
                    yield chunk

                latency = (time.time() - start) * 1000

                if final_result and final_result.get("success"):
                    self._record_usage(
                        model_name, True,
                        input_tokens=final_result.get("usage", {}).get("input_tokens", 0),
                        output_tokens=final_result.get("usage", {}).get("output_tokens", 0),
                        latency_ms=latency,
                    )
                    final_result["routed_model"] = model_name
                    return final_result
                else:
                    self._record_usage(model_name, False)
                    last_error = final_result.get("error", "unknown") if final_result else "unknown"

            except Exception as e:
                last_error = str(e)
                self._record_usage(model_name, False)

        # 所有模型失败
        yield "\n\n[错误] 所有候选模型均不可用，请检查「账户设置 → AI 模型」中的端点与密钥配置。"

    def quick_chat(
        self,
        prompt: str,
        max_tokens: int = 1024,
        task_type: str = "quick",
    ) -> str:
        """快速对话（自动降级）"""
        result = self.chat(
            system_prompt="你是一个有帮助的AI助手。",
            user_prompt=prompt,
            task_type=task_type,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        if result.get("success"):
            return result["content"]
        return f"[错误] {result.get('error', '所有模型不可用')}"

    # ---- 统计 ----

    def get_usage_stats(self) -> dict:
        """获取用量统计"""
        self._refresh_if_stale()
        result = {}
        total_cost = 0.0
        with self._lock:
            for name, stats in self._usage.items():
                entry = self._registry.get(
                    name, ModelEntry(name=name, provider="unknown", priority=99)
                )
                input_cost = (stats.total_input_tokens / 1000) * entry.cost_per_1k_input
                output_cost = (stats.total_output_tokens / 1000) * entry.cost_per_1k_output
                avg_latency = stats.total_latency_ms / stats.success_calls if stats.success_calls > 0 else 0
                total_cost += input_cost + output_cost
                result[name] = {
                    "total_calls": stats.total_calls,
                    "success_calls": stats.success_calls,
                    "fail_calls": stats.fail_calls,
                    "success_rate": stats.success_calls / stats.total_calls if stats.total_calls > 0 else 0,
                    "total_input_tokens": stats.total_input_tokens,
                    "total_output_tokens": stats.total_output_tokens,
                    "avg_latency_ms": round(avg_latency, 1),
                    "estimated_cost_usd": round(input_cost + output_cost, 4),
                    "cost_is_estimate": True,
                    "circuit_open": self._is_circuit_open(name),
                }
        return {
            "models": result,
            "total_estimated_cost_usd": round(total_cost, 4),
            "endpoint": config.effective_llm.base_url,
            "preset": config.effective_llm.preset,
            "source": config.effective_llm.source,
        }

    def reset_stats(self):
        """重置用量统计"""
        with self._lock:
            self._usage = defaultdict(UsageStats)
            self._consecutive_failures = defaultdict(int)
            self._circuit_breakers = {}


# ============================================================
# 单例
# ============================================================

_model_router: Optional[ModelRouter] = None
_model_router_lock = threading.Lock()


def get_model_router() -> ModelRouter:
    """获取 ModelRouter 全局单例（线程安全）"""
    global _model_router
    if _model_router is None:
        with _model_router_lock:
            if _model_router is None:
                _model_router = ModelRouter()
    return _model_router
