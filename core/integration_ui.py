"""
模型与数据源配置界面
====================
「自带模型（BYOK）」与「自带行情数据源」的统一配置组件。

设计原则：
- 非 LLM 功能（筛选 / 回测 / 费率计算）在未配置密钥时**依然完全可用**，
  保证自部署用户开箱即用不是一句空话；只有 AI 分析类功能需要配置。
- 界面一律只回显密钥掩码，不回传明文。
- 支持一键测试连通性，避免「配了半天不知道对不对」。

使用方式:
    from core.integration_ui import render_integration_settings
    render_integration_settings()
"""

from __future__ import annotations

import streamlit as st

from .llm_presets import list_presets, get_preset, DEFAULT_PRESET


# 常见数据源及其特点（供 UI 说明）
DATA_PROVIDERS = [
    ("akshare", "AKShare（免费免 token）", "默认数据源，覆盖全市场公募基金。免注册，但公共接口偶有限流，建议开启本地缓存。"),
    ("tushare", "Tushare（需 token，数据质量更好）", "需在 tushare.pro 免费注册获取 token。积分制，持仓与宏观数据更规整。"),
    ("eastmoney", "东方财富直连", "直接抓取天天基金网页接口，无需 token，作为 AKShare 的补充通道。"),
    ("baostock", "Baostock（免费免 token）", "日线数据为主，稳定性好，适合做长周期回测。"),
]


def _test_llm_connection(preset_key: str, base_url: str, api_key: str, model: str, protocol: str) -> tuple[bool, str]:
    """
    发一次极小的请求验证连通性。

    Returns:
        (是否成功, 提示信息)
    """
    if not model:
        return False, "请先填写模型名称"
    preset_obj = get_preset(preset_key)
    needs_key = preset_obj.requires_key if preset_obj else True
    if needs_key and not api_key:
        return False, "请先填写 API Key"

    try:
        if protocol == "anthropic":
            from anthropic import Anthropic
            client = Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model, max_tokens=16,
                messages=[{"role": "user", "content": "回复 ok"}],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            return True, f"连通成功，模型返回：{text.strip()[:40] or '(空)'}"

        from openai import OpenAI
        kwargs = {"api_key": api_key or "not-needed"}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        resp = client.chat.completions.create(
            model=model, max_tokens=16,
            messages=[{"role": "user", "content": "回复 ok"}],
        )
        text = (resp.choices[0].message.content or "").strip()
        return True, f"连通成功，模型返回：{text[:40] or '(空)'}"
    except Exception as e:
        msg = str(e)
        if len(msg) > 300:
            msg = msg[:300] + "…"
        return False, f"连接失败：{msg}"


def render_llm_settings() -> None:
    """渲染「AI 模型」配置区（BYOK）。"""
    from .user_integrations import (
        resolve_llm_config, save_user_llm, clear_user_llm, mask_key, clear_session_override,
    )

    eff = resolve_llm_config()
    presets = list_presets()
    keys = [p.key for p in presets]
    labels = {p.key: p.label for p in presets}

    # ---- 当前状态 ----
    if eff.is_configured:
        st.success(
            f"当前生效：**{labels.get(eff.preset, eff.preset)}** · 模型 `{eff.model}` · "
            f"来源：{eff.source_label}"
        )
    else:
        st.warning(
            "尚未配置可用的 AI 模型。**筛选、回测、费率计算等本地功能不受影响，可直接使用**；"
            "仅 AI 分析类功能需要配置后才会启用。"
        )

    idx = keys.index(eff.preset) if eff.preset in keys else 0
    sel = st.selectbox(
        "模型服务商",
        options=keys,
        index=idx,
        format_func=lambda k: labels.get(k, k),
        key="byok_preset",
    )
    preset = get_preset(sel)

    if preset and preset.note:
        st.caption(f"ℹ️ {preset.note}")

    # ---- 表单 ----
    with st.form("byok_llm_form"):
        base_url = st.text_input(
            "接口地址（base_url）",
            value=eff.base_url if eff.preset == sel else (preset.base_url if preset else ""),
            placeholder="https://api.deepseek.com/v1",
            help="OpenAI 兼容端点。Docker 部署时若要连宿主机的 Ollama，请用 http://host.docker.internal:11434/v1",
        )

        model_options = list(preset.models) if preset and preset.models else []
        cur_model = eff.model if eff.preset == sel else (model_options[0] if model_options else "")
        if model_options:
            model = st.selectbox(
                "模型",
                options=model_options,
                index=model_options.index(cur_model) if cur_model in model_options else 0,
                help="下拉为常用模型，也可在下方自定义模型名",
            )
        else:
            model = st.text_input("模型名称", value=cur_model, placeholder="填写服务端声明的模型名")

        custom_model = st.text_input(
            "自定义模型名（可选，填写后覆盖上方选择）",
            value="",
            placeholder="留空则使用上方选择的模型",
        )

        api_key = st.text_input(
            "API Key",
            value=mask_key(eff.api_key) if eff.api_key else "",
            type="password",
            placeholder="本地 Ollama / vLLM 可留空",
            help="仅保存在你自己的数据库中，界面只回显掩码。留空且未修改则保持原值。",
        )

        if preset and preset.api_key_url:
            st.caption(f"🔑 获取密钥：{preset.api_key_url}")

        c1, c2 = st.columns([1, 1])
        with c1:
            submitted = st.form_submit_button("💾 保存配置", use_container_width=True, type="primary")
        with c2:
            tested = st.form_submit_button("🔌 测试连通性", use_container_width=True)

        final_model = (custom_model.strip() or model or "").strip()

        if submitted:
            ok = save_user_llm({
                "preset": sel,
                "base_url": base_url.strip(),
                "api_key": api_key.strip(),
                "model": final_model,
                "protocol": preset.protocol if preset else "openai",
            })
            clear_session_override()
            if ok:
                st.success("✅ 已保存。配置立即生效，无需重启。")
                st.rerun()
            else:
                st.error("保存失败，请检查服务端日志。")

        if tested:
            with st.spinner("正在测试连通性…"):
                ok, msg = _test_llm_connection(
                    sel, base_url.strip(), api_key.strip(), final_model,
                    preset.protocol if preset else "openai",
                )
            (st.success if ok else st.error)(msg)

    st.caption(
        "💡 优先级：本次会话中的临时选择 > 此处保存的账户配置 > 服务端 `.env`。"
        "自部署用户直接在 `.env` 里配置即可，此处无需重复填写。"
    )

    if st.button("↩️ 清除我的模型配置（回退到服务端默认）", key="byok_clear"):
        clear_user_llm()
        clear_session_override()
        st.success("已清除，将使用服务端 .env 中的配置。")
        st.rerun()


def render_data_source_settings() -> None:
    """渲染「行情数据源」配置区。"""
    from .user_integrations import (
        resolve_data_source_config, save_user_data_source, mask_key,
    )
    from .data_sources import list_available_sources

    cfg = resolve_data_source_config()
    available = list_available_sources()  # [{"name","label","available","reason"}]

    st.markdown("**当前数据源可用性检测**")
    for item in available:
        if item["available"]:
            st.caption(f"🟢 {item['label']} —— 可用")
        else:
            st.caption(f"⚪ {item['label']} —— 不可用（{item['reason']}）")

    provider_keys = [p[0] for p in DATA_PROVIDERS]
    provider_labels = {p[0]: p[1] for p in DATA_PROVIDERS}

    cur = cfg.get("provider", "akshare")
    idx = provider_keys.index(cur) if cur in provider_keys else 0

    with st.form("byok_data_form"):
        sel = st.selectbox(
            "首选数据源",
            options=provider_keys,
            index=idx,
            format_func=lambda k: provider_labels.get(k, k),
            key="byok_data_provider",
        )
        desc = dict((p[0], p[2]) for p in DATA_PROVIDERS).get(sel, "")
        if desc:
            st.caption(f"ℹ️ {desc}")

        token = st.text_input(
            "Tushare Token（仅选择 Tushare 时需要）",
            value=mask_key(cfg.get("tushare_token", "")) if cfg.get("tushare_token") else "",
            type="password",
            help="在 tushare.pro 注册后于个人中心获取。留空且未修改则保持原值。",
        )

        cache_ttl = st.number_input(
            "本地缓存有效期（秒）",
            min_value=0, max_value=86400,
            value=int(cfg.get("cache_ttl", 300) or 300),
            step=60,
            help="行情结果本地缓存时长。日线数据可设大一些（如 3600），实时估值建议 180~300 秒。"
                 "缓存能显著减少对公共数据源的请求，避免被限流。",
        )

        saved = st.form_submit_button("💾 保存数据源配置", use_container_width=True, type="primary")
        if saved:
            ok = save_user_data_source({
                "provider": sel,
                "tushare_token": token.strip(),
                "cache_ttl": int(cache_ttl),
            })
            if ok:
                st.success("✅ 已保存。下次取数即按新配置执行。")
                try:
                    st.session_state.pop("_data_override", None)
                except Exception:
                    pass
                from .data_sources import clear_cache
                clear_cache()
                st.rerun()
            else:
                st.error("保存失败，请检查服务端日志。")


def render_integration_settings(show_data_source: bool = True) -> None:
    """渲染完整集成配置（模型 + 数据源）。"""
    st.markdown("### 🧠 AI 模型（自带密钥）")
    render_llm_settings()

    if show_data_source:
        st.divider()
        st.markdown("### 📡 行情数据源")
        render_data_source_settings()
