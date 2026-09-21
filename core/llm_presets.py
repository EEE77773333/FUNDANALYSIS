"""
LLM 提供商预设注册表
====================
系统统一走 **OpenAI 兼容协议**（base_url + api_key + model 三元组），
因此云端 API 与本地推理服务可以用同一套代码调用。

覆盖范围：
- 云端 API：DeepSeek / 通义千问 / 智谱 GLM / Kimi / OpenAI / 硅基流动 / OpenRouter
- 本地模型：Ollama / vLLM / LM Studio（零成本跑 Qwen、DeepSeek-R1 蒸馏版）
- 原生协议：Anthropic Claude（非 OpenAI 兼容，单独走 anthropic SDK）

新增提供商只需在 `LLM_PRESETS` 追加一条记录，**无需改动调用层**。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class LLMPreset:
    """单个 LLM 提供商的接入预设。"""

    key: str                      # 配置键（用于 .env 的 LLM_PRESET 与 UI 下拉）
    label: str                    # 中文显示名
    base_url: str                 # 端点地址（OpenAI 兼容）
    protocol: str                 # "openai" | "anthropic"
    models: Tuple[str, ...] = ()  # 常用模型（供 UI 下拉，用户仍可自行填写）
    api_key_url: str = ""         # 密钥申请地址（UI 引导用）
    requires_key: bool = True     # 本地推理服务通常无需 key
    note: str = ""                # 补充说明

    @property
    def is_local(self) -> bool:
        """是否为本地推理服务（不消耗云端额度）。"""
        return self.base_url.startswith(("http://localhost", "http://127.0.0.1", "http://host.docker.internal"))


# ============================================================
# 预设注册表
# ============================================================

LLM_PRESETS: Dict[str, LLMPreset] = {
    # ---------- 云端 API ----------
    "deepseek": LLMPreset(
        key="deepseek",
        label="DeepSeek 深度求索",
        base_url="https://api.deepseek.com/v1",
        protocol="openai",
        models=("deepseek-chat", "deepseek-reasoner"),
        api_key_url="https://platform.deepseek.com/api_keys",
        note="性价比高，中文金融语境表现好，推荐默认",
    ),
    "qwen": LLMPreset(
        key="qwen",
        label="通义千问（阿里云 DashScope）",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        protocol="openai",
        models=("qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"),
        api_key_url="https://bailian.console.aliyun.com/",
    ),
    "glm": LLMPreset(
        key="glm",
        label="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        protocol="openai",
        models=("glm-4-plus", "glm-4-flash", "glm-4-long"),
        api_key_url="https://open.bigmodel.cn/usercenter/apikeys",
    ),
    "kimi": LLMPreset(
        key="kimi",
        label="Kimi（月之暗面）",
        base_url="https://api.moonshot.cn/v1",
        protocol="openai",
        models=("moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"),
        api_key_url="https://platform.moonshot.cn/console/api-keys",
    ),
    "openai": LLMPreset(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        protocol="openai",
        models=("gpt-4o", "gpt-4o-mini"),
        api_key_url="https://platform.openai.com/api-keys",
    ),
    "siliconflow": LLMPreset(
        key="siliconflow",
        label="硅基流动 SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        protocol="openai",
        models=("deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"),
        api_key_url="https://cloud.siliconflow.cn/account/ak",
        note="聚合多家开源模型，常有大额免费额度",
    ),
    "openrouter": LLMPreset(
        key="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        protocol="openai",
        models=("openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"),
        api_key_url="https://openrouter.ai/keys",
        note="一个 key 打通多家模型",
    ),
    "anthropic": LLMPreset(
        key="anthropic",
        label="Anthropic Claude",
        base_url="",  # 使用 anthropic 原生 SDK，无需 base_url
        protocol="anthropic",
        models=("claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5"),
        api_key_url="https://console.anthropic.com/",
        note="走原生协议，非 OpenAI 兼容",
    ),

    # ---------- 本地推理（零 API 成本）----------
    "ollama": LLMPreset(
        key="ollama",
        label="Ollama（本地）",
        base_url="http://localhost:11434/v1",
        protocol="openai",
        models=("qwen2.5:7b", "qwen2.5:14b", "deepseek-r1:7b", "llama3.1:8b"),
        requires_key=False,
        note="本地跑模型，零 API 成本；Docker 部署需把 localhost 换成 host.docker.internal",
    ),
    "vllm": LLMPreset(
        key="vllm",
        label="vLLM（本地/自建）",
        base_url="http://localhost:8000/v1",
        protocol="openai",
        models=(),
        requires_key=False,
        note="高吞吐自建推理服务，模型名填你启动时指定的 --served-model-name",
    ),
    "lmstudio": LLMPreset(
        key="lmstudio",
        label="LM Studio（本地桌面）",
        base_url="http://localhost:1234/v1",
        protocol="openai",
        models=(),
        requires_key=False,
    ),

    # ---------- 兜底 ----------
    "custom": LLMPreset(
        key="custom",
        label="自定义 OpenAI 兼容端点",
        base_url="",
        protocol="openai",
        models=(),
        requires_key=False,
        note="任何兼容 /chat/completions 的服务都可以接入",
    ),
}

# 默认预设
DEFAULT_PRESET = "deepseek"


# ============================================================
# 便捷访问
# ============================================================

def get_preset(key: Optional[str]) -> Optional[LLMPreset]:
    """按 key 取预设，不存在返回 None。"""
    if not key:
        return None
    return LLM_PRESETS.get(str(key).strip().lower())


def list_presets(include_custom: bool = True) -> List[LLMPreset]:
    """列出全部预设（按 UI 展示顺序）。"""
    order = [
        "deepseek", "qwen", "glm", "kimi", "openai", "siliconflow", "openrouter",
        "anthropic", "ollama", "vllm", "lmstudio", "custom",
    ]
    out = [LLM_PRESETS[k] for k in order if k in LLM_PRESETS]
    if not include_custom:
        out = [p for p in out if p.key != "custom"]
    return out


def preset_choices() -> List[Tuple[str, str]]:
    """返回 (key, label) 列表，供 Streamlit selectbox 使用。"""
    return [(p.key, p.label) for p in list_presets()]


def infer_preset(base_url: str, protocol: str = "openai") -> str:
    """
    根据 base_url 反推预设 key（用于兼容只填了 DEEPSEEK_* 的老配置）。
    """
    if protocol == "anthropic":
        return "anthropic"
    if not base_url:
        return DEFAULT_PRESET
    url = base_url.lower().rstrip("/")
    for p in LLM_PRESETS.values():
        if p.base_url and p.base_url.lower().rstrip("/") in url:
            return p.key
    # 常见别名兜底
    if "deepseek" in url:
        return "deepseek"
    if "dashscope" in url or "aliyuncs" in url:
        return "qwen"
    if "bigmodel" in url or "zhipu" in url:
        return "glm"
    if "moonshot" in url:
        return "kimi"
    if "localhost" in url or "127.0.0.1" in url:
        return "ollama"
    return "custom"
