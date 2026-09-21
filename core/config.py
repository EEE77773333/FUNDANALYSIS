"""
系统配置管理
============
负责加载环境变量、验证必需配置项、提供全局配置访问。

LLM 配置采用「OpenAI 兼容协议优先」的设计：
    - 任意 OpenAI 兼容端点（DeepSeek / 通义 / 智谱 / Kimi / OpenAI / Ollama / vLLM …）
      统一用 base_url + api_key + model 三元组描述
    - Anthropic Claude 走原生协议，单独标识
    - 旧的 DEEPSEEK_* / ANTHROPIC_* 变量继续可用（向后兼容，自动反推预设）

配置优先级（高 → 低）：
    1. 会话内临时覆盖（UI 里临时试模型）
    2. 当前登录用户的账户配置（BYOK，见 core/user_integrations.py）
    3. 环境变量 .env
    4. config.yaml（可选）
    5. 内置默认值
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from dataclasses import dataclass, field
from typing import Optional, Literal, Any, Dict

from .llm_presets import get_preset, infer_preset, DEFAULT_PRESET


# 加载 .env 文件（优先当前目录，其次项目根目录）
def _load_env():
    """逐级查找并加载 .env 文件。"""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).parent.parent / ".env",
    ]
    for p in candidates:
        if p.exists():
            load_dotenv(p)
            return str(p)
    return None


_env_path = _load_env()


# ============================================================
# 可选：config.yaml 覆盖层
# ============================================================

def _load_yaml_config() -> Dict[str, Any]:
    """
    若项目根存在 config.yaml，读取其中的 llm / data / streamlit 段作为额外覆盖。
    该文件不存在时静默跳过，不影响 .env 单一路径的部署方式。
    """
    candidates = [
        Path(__file__).parent.parent / "config.yaml",
        Path.cwd() / "config.yaml",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            import yaml
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


_yaml_cfg = _load_yaml_config()
_yaml_llm = _yaml_cfg.get("llm") or {}
_yaml_data = _yaml_cfg.get("data") or {}


def _yc(section: Dict[str, Any], key: str, env_name: str, default: str = "") -> str:
    """YAML 值优先于环境变量（YAML 是显式文件，比 .env 更"有意为之"）。"""
    val = section.get(key)
    if val:
        return str(val)
    return os.getenv(env_name, default)


# ============================================================
# LLM 配置解析（环境变量 + YAML → 规范化三元组）
# ============================================================

def _build_llm_env_config() -> Dict[str, str]:
    """
    把 .env / config.yaml 里的各种写法归一成
    {preset, base_url, api_key, model, protocol}。
    """
    # --- api_key：LLM_API_KEY 优先，其次各厂商专用变量 ---
    api_key = (
        _yc(_yaml_llm, "api_key", "LLM_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY", "")
        or os.getenv("ANTHROPIC_API_KEY", "")
    ).strip()

    # --- protocol ---
    protocol = (_yc(_yaml_llm, "protocol", "LLM_PROTOCOL") or "").strip().lower()
    if not protocol:
        protocol = "anthropic" if (os.getenv("ANTHROPIC_API_KEY") and not os.getenv("DEEPSEEK_API_KEY") and not _yc(_yaml_llm, "api_key", "LLM_API_KEY")) else "openai"

    # --- preset ---
    preset = (_yc(_yaml_llm, "preset", "LLM_PRESET") or "").strip().lower()

    # --- base_url ---
    base_url = (_yc(_yaml_llm, "base_url", "LLM_BASE_URL") or "").strip()
    if not base_url:
        if protocol == "anthropic":
            base_url = ""
        elif os.getenv("DEEPSEEK_BASE_URL"):
            base_url = os.getenv("DEEPSEEK_BASE_URL", "").strip()
        else:
            base_url = ""

    # --- 反推 preset ---
    if not preset:
        if base_url or api_key:
            preset = infer_preset(base_url, protocol)
        else:
            preset = DEFAULT_PRESET

    preset_obj = get_preset(preset)
    if preset_obj:
        if not base_url:
            base_url = preset_obj.base_url
        if not protocol or protocol not in ("openai", "anthropic"):
            protocol = preset_obj.protocol

    # --- model ---
    model = (_yc(_yaml_llm, "model", "LLM_MODEL") or "").strip()
    if not model:
        if preset == "deepseek":
            model = os.getenv("DEEPSEEK_MODEL", "").strip()
        elif preset == "anthropic":
            model = os.getenv("ANTHROPIC_MODEL", "").strip()
    if not model and preset_obj and preset_obj.models:
        model = preset_obj.models[0]

    return {
        "preset": preset,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "protocol": protocol or "openai",
    }


_llm_env = _build_llm_env_config()


@dataclass
class Config:
    """全局配置单例。"""

    # ---- LLM（规范化后的通用配置，推荐使用）----
    llm_preset: str = _llm_env["preset"]
    llm_base_url: str = _llm_env["base_url"]
    llm_api_key: str = _llm_env["api_key"]
    llm_model: str = _llm_env["model"]
    llm_protocol: str = _llm_env["protocol"]

    # ---- 旧版字段（保留以兼容既有代码与配置文件）----
    ai_provider: str = field(
        default_factory=lambda: "anthropic" if _llm_env["protocol"] == "anthropic" else "deepseek"
    )
    deepseek_api_key: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "")
    )
    deepseek_base_url: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )
    deepseek_model: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    )
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    )

    # ---- 行情数据源 ----
    tushare_token: str = field(
        default_factory=lambda: _yc(_yaml_data, "tushare_token", "TUSHARE_TOKEN")
    )
    data_provider: str = field(
        default_factory=lambda: (_yc(_yaml_data, "provider", "DATA_PROVIDER", "akshare") or "akshare").lower()
    )
    quote_cache_ttl: int = field(
        default_factory=lambda: int(_yc(_yaml_data, "cache_ttl", "QUOTE_CACHE_TTL", "300") or 300)
    )

    # ---- 项目路径 ----
    project_root: Path = field(
        default_factory=lambda: Path(__file__).parent.parent
    )
    prompts_dir: Path = field(
        default_factory=lambda: Path(__file__).parent.parent / "prompts"
    )

    # ---- Streamlit ----
    streamlit_port: int = field(
        default_factory=lambda: int(os.getenv("STREAMLIT_SERVER_PORT", "8501"))
    )

    # ---- 数据缓存 ----
    cache_ttl_seconds: int = 300

    def __post_init__(self):
        """静默初始化，不做验证。API Key 缺失在实际调用 AI 时才提示。"""
        pass

    # ---- 生效配置（含 BYOK 覆盖）----

    @property
    def effective_llm(self):
        """
        解析当前真正生效的 LLM 配置（会话 → 用户库 → 环境变量）。
        返回 EffectiveLLMConfig，见 core/user_integrations.py。
        """
        try:
            from .user_integrations import resolve_llm_config
            return resolve_llm_config()
        except Exception:
            from .user_integrations import EffectiveLLMConfig
            return EffectiveLLMConfig(
                preset=self.llm_preset,
                base_url=self.llm_base_url,
                api_key=self.llm_api_key,
                model=self.llm_model,
                protocol=self.llm_protocol,
                source="env",
            )

    @property
    def is_configured(self) -> bool:
        """检查生效的 LLM 配置是否可用（本地推理服务不要求 key）。"""
        return self.effective_llm.is_configured

    @property
    def active_api_key(self) -> str:
        """返回生效的 API Key。"""
        return self.effective_llm.api_key

    @property
    def active_model(self) -> str:
        """返回生效的模型名称。"""
        ae = self.effective_llm
        return ae.model or self.llm_model or "未配置"

    @property
    def active_base_url(self) -> str:
        return self.effective_llm.base_url

    @property
    def active_protocol(self) -> str:
        return self.effective_llm.protocol

    @property
    def api_key_masked(self) -> str:
        """返回脱敏后的 API Key。"""
        from .user_integrations import mask_key
        key = self.active_api_key
        return mask_key(key) or "未配置"

    @property
    def available_models(self) -> list:
        """
        返回当前预设的常用模型列表。
        仅作 UI 建议，用户仍可自由填写任意模型名。
        """
        preset_obj = get_preset(self.effective_llm.preset)
        if preset_obj and preset_obj.models:
            return list(preset_obj.models)
        return [self.active_model] if self.active_model else []


# 全局配置实例
config = Config()
