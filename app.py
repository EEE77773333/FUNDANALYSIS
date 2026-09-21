"""
基金智能分析系统 — 主入口
=============================
基于用户自配置 LLM + 多源行情数据的基金分析平台。
覆盖从宏观研判到微观选基的完整投资决策闭环。

启动方式:
    streamlit run app.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import streamlit as st
from core.ui_theme import inject_global_theme_css, render_theme_toggle, get_color_mode

# ============================================================
# 页面配置（必须是第一个 Streamlit 命令）
# ============================================================
st.set_page_config(
    page_title="基金智能分析系统",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": None,
        "Report a bug": None,
        "About": (
            "# 基金智能分析系统 v2.4（开源版）\n\n"
            "模型与行情数据源均可自行配置，支持 DeepSeek / 通义 / 智谱 / Kimi / "
            "OpenAI / 本地 Ollama 等。\n\n"
            "覆盖五大类基金分析 + 资产配置 + 组合诊断\n\n"
            "License: AGPL-3.0\n\n"
            "⚠️ 本系统仅供学习研究，不构成投资建议。"
        ),
    },
)

# ============================================================
# 侧边栏在桌面端保持展开，由下方 CSS @media (min-width: 769px) 控制；
# 移动端交回 Streamlit 原生折叠行为。
# ============================================================
import streamlit.components.v1 as _components

# ============================================================
# 全局 CSS — 浅色 / 深色主题（侧边栏按钮切换）
# ============================================================
inject_global_theme_css()
# 返回顶部 JS — 组件运行在 iframe 内，需操作父文档与真实滚动容器
_components.html("""
<script>
(function(){
    var doc = window.parent.document;
    if (doc.getElementById('back-to-top')) return;
    var scroller = doc.querySelector('[data-testid="stMain"]');
    var btn = doc.createElement('div');
    btn.id = 'back-to-top';
    btn.innerHTML = '⬆';
    btn.title = '返回顶部';
    btn.onclick = function(){ scroller.scrollTo({top:0,behavior:'smooth'}); };
    doc.body.appendChild(btn);
    scroller.addEventListener('scroll', function(){
        if(scroller.scrollTop > 300){ btn.classList.add('show'); }
        else { btn.classList.remove('show'); }
    });
})();
</script>
""", height=0)


# ============================================================
# 主页内容
# ============================================================

def render_main_page():
    """渲染主页内容。"""

    # 多用户下首页也要求登录，以便展示个人工作台
    try:
        from core.middleware import require_auth
        require_auth()
    except Exception:
        pass

    try:
        from core.workspace_ui import render_workbench_home
        if render_workbench_home():
            # 工作台用户仍保留精简快捷入口
            from core.ui_components import section_header
            from core.nav_catalog import workbench_quick_links
            section_header("快速入口")
            all_pages = workbench_quick_links()
            per_row = 5
            for start in range(0, len(all_pages), per_row):
                cols = st.columns(per_row)
                for offset, (icon, name, page) in enumerate(all_pages[start:start + per_row]):
                    with cols[offset]:
                        st.page_link(page, label=name, icon=icon, use_container_width=True)
            st.markdown("""
            <div class="risk-disclaimer">
                <div class="title">⚠️ 风险提示</div>
                <div class="body">
                    本系统仅供学习研究使用，<strong>不构成任何直接或间接的投资建议</strong>。
                </div>
            </div>
            """, unsafe_allow_html=True)
            return
    except Exception:
        pass

    # ── Hero 区域 ──
    st.markdown("""
    <div class="hero-section">
        <div class="hero-title">基金智能分析系统</div>
        <div class="hero-subtitle">
            自选大模型 + 自选行情源，
            覆盖宏观研判 → 基金筛选 → Agent分析 → 组合诊断 → 持续监控的<strong>全链路投资决策平台</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 实时指数条 + 估值分位 ──
    try:
        import requests
        idx_map = {"上证":"s_sh000001","深证":"s_sz399001","创业板":"s_sz399006","科创50":"s_sh000688","沪深300":"s_sh000300","中证500":"s_sh000905"}
        idx_html = ""
        for name, code in idx_map.items():
            try:
                r = requests.get(f"https://hq.sinajs.cn/list={code}",
                    headers={"User-Agent":"Mozilla/5.0","Referer":"https://finance.sina.com.cn"},
                    timeout=5, proxies={"http":None,"https":None})
                r.encoding = "gb2312"
                parts = r.text.split('"')[1].split(",")
                price, chg = float(parts[1]), float(parts[3])
                color = "#DC2626" if chg >= 0 else "#16A34A"
                idx_html += f'<span style="margin-right:1.2rem;white-space:nowrap;"><b>{name}</b> <span style="color:{color};">{price:.0f} {chg:+.2f}%</span></span>'
            except: pass

        # 估值分位（仅大指数，缓存读取）
        pe_html = ""
        for idx_name in ["沪深300", "中证500", "创业板指"]:
            try:
                from core.data_fetcher import get_fetcher
                val = get_fetcher().get_index_valuation(idx_name)
                pe_pct = val.get("PE百分位")
                if pe_pct is not None:
                    if pe_pct < 30:
                        dot = "🟢"
                    elif pe_pct < 70:
                        dot = "🟡"
                    else:
                        dot = "🔴"
                    pe_html += f'<span style="margin-right:1rem;white-space:nowrap;font-size:0.85rem;">{dot} {idx_name} PE {pe_pct}%</span>'
            except: pass

        if idx_html:
            bar = idx_html
            if pe_html:
                bar += f'<span style="margin-left:0.5rem;padding-left:0.5rem;border-left:2px solid #E2E8F0;">{pe_html}</span>'
            st.markdown(f'<div class="index-ticker-bar">{bar}</div>', unsafe_allow_html=True)
        else:
            st.caption("📡 实时行情数据暂不可用，请检查网络连接")
    except Exception:
        st.caption("📡 实时行情数据暂不可用，请检查网络连接")

    # ── 系统架构 ──
    with st.expander("🏗️ 系统架构", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("""
            <div class="card card-accent">
                <div class="card-icon">📡</div>
                <div class="card-title">数据采集层</div>
                <div class="card-body">
                    多源行情接入（东财/akshare/baostock）<br>
                    实时净值估算 API<br>
                    宏观指标 CPI/PPI/PMI<br>
                    指数 PE/PB 历史分位
                </div>
            </div>
            """, unsafe_allow_html=True)
        with c2:
            st.markdown("""
            <div class="card card-accent">
                <div class="card-icon">🧠</div>
                <div class="card-title">分析引擎层</div>
                <div class="card-body">
                    17 个分析模板<br>
                    多模型流式分析<br>
                    夏普 / 回撤 / Alpha / Beta<br>
                    10 Agent 多维度协作
                </div>
            </div>
            """, unsafe_allow_html=True)
        with c3:
            st.markdown("""
            <div class="card card-accent">
                <div class="card-icon">🖥️</div>
                <div class="card-title">交互展示层</div>
                <div class="card-body">
                    Streamlit 多页框架<br>
                    交互式数据看板<br>
                    参数化智能筛选<br>
                    一键导出分析报告
                </div>
            </div>
            """, unsafe_allow_html=True)

    # ── 统计仪表盘 ──
    st.markdown("### 系统概览")
    st.markdown("""
    <div class="stat-grid">
        <div class="stat-item">
            <div class="stat-value">30</div>
            <div class="stat-label">功能页面</div>
            <div class="stat-delta">7 大分组全覆盖</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">27,000+</div>
            <div class="stat-label">覆盖基金</div>
            <div class="stat-delta">全市场公募基金</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">17</div>
            <div class="stat-label">分析模板</div>
            <div class="stat-delta">7 YAML + 10 Agent</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">15+</div>
            <div class="stat-label">金融指标</div>
            <div class="stat-delta">夏普 / 回撤 / Alpha / Beta</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">2</div>
            <div class="stat-label">数据源</div>
            <div class="stat-delta">东财 / akshare / baostock</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)

    # ── 漏斗式三步法 ──
    st.markdown("### 推荐工作流：漏斗式三步法")

    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown("""
        <div class="step-card card-step1">
            <span class="step-number n1">1</span>
            <div class="card-title">定框架</div>
            <div class="card-body">
                输入财务状况、投资期限和风险承受能力，AI 生成个性化股债配比方案。
            </div>
            <div class="card-footer">
                → 资产配置框架
            </div>
        </div>
        """, unsafe_allow_html=True)
    with s2:
        st.markdown("""
        <div class="step-card card-step2">
            <span class="step-number n2">2</span>
            <div class="card-title">填标的</div>
            <div class="card-body">
                在战略框架内，按基金类型分别筛选具体标的，AI 多维度深度分析每只基金。
            </div>
            <div class="card-footer">
                → 排名精选 / 债券筛选 / 指数筛选 / 主动权益 / QDII配置
            </div>
        </div>
        """, unsafe_allow_html=True)
    with s3:
        st.markdown("""
        <div class="step-card card-step3">
            <span class="step-number n3">3</span>
            <div class="card-title">做体检</div>
            <div class="card-body">
                诊断现有持仓的行业集中度、风格漂移、费率效率，给出优化调仓方案。
            </div>
            <div class="card-footer">
                → 组合诊断优化 + 持续监控预警
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr class='section-divider'>", unsafe_allow_html=True)

    # ── 快速入口（15个核心入口，每行5列）──
    st.markdown("### 快速入口")
    all_pages = [
        ("🏆", "排名精选", "pages/10_基金排名精选.py"),
        ("📈", "宏观研判", "pages/01_宏观行业研判.py"),
        ("📊", "债券筛选", "pages/02_债券基金筛选.py"),
        ("📉", "指数筛选", "pages/03_指数基金筛选.py"),
        ("🎯", "主动权益", "pages/04_主动权益筛选.py"),
        ("🌍", "QDII配置", "pages/05_QDII基金筛选.py"),
        ("🔬", "FAMAS分析", "pages/08_FAMAS单基金深度分析.py"),
        ("🚨", "监控预警", "pages/09_持续监控预警.py"),
        ("📡", "盘中估值", "pages/27_盘中估值中心.py"),
        ("🌊", "主题资金", "pages/28_主题资金流雷达.py"),
        ("💼", "我的组合", "pages/19_组合管理.py"),
        ("⚖️", "赛道再平衡", "pages/30_赛道再平衡.py"),
        ("⚔️", "基金PK", "pages/11_基金PK擂台.py"),
        ("🎲", "蒙特卡洛", "pages/26_蒙特卡洛模拟.py"),
        ("📚", "分析历史", "pages/22_分析历史.py"),
    ]
    per_row = 5
    for start in range(0, len(all_pages), per_row):
        cols = st.columns(per_row)
        for offset, (icon, name, page) in enumerate(all_pages[start:start + per_row]):
            with cols[offset]:
                st.page_link(page, label=name, icon=icon, use_container_width=True)

    # ── 风险提示 ──
    st.markdown("""
    <div class="risk-disclaimer">
        <div class="title">⚠️ 风险提示</div>
        <div class="body">
            本系统仅供学习研究使用，<strong>不构成任何直接或间接的投资建议</strong>。
            AI 分析基于历史数据与公开信息，金融市场瞬息万变，过去表现不代表未来收益。
            数据源依赖第三方网站（天天基金/东方财富），可能在源站改版时短期失效。
            基金投资有风险，在做出实际交易决策前，请结合自身独立判断与风险承受能力。
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 页脚 ──
    st.markdown("""
    <div class="app-footer">
        基金智能分析系统 v2.4 &nbsp;·&nbsp; 开源版 AGPL-3.0 &nbsp;·&nbsp; 模型与数据源可自行配置
    </div>
    """, unsafe_allow_html=True)
    import base64 as _base64
    _icon_path = Path(__file__).parent / "static" / "beian.png"
    _icon_b64 = _base64.b64encode(_icon_path.read_bytes()).decode()
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:center;gap:6px;margin-top:0.3rem;">
        <img src="data:image/png;base64,{_icon_b64}" width="20" style="display:block;">
        <a href="https://beian.mps.gov.cn/#/query/webSearch?code=21021102001922" target="_blank" rel="noopener noreferrer"
           style="color:#94A3B8;font-size:0.75rem;text-decoration:none;">
            辽公网安备21021102001922号
        </a>
    </div>
    """, unsafe_allow_html=True)



# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    from core.nav_catalog import build_streamlit_nav

    home = st.Page(render_main_page, title="工作台", icon="🏠", default=True)
    include_admin = True
    try:
        from core.middleware import is_admin
        # 未登录时不展示管理页；登录后按角色
        if st.session_state.get("user"):
            include_admin = bool(is_admin())
        else:
            include_admin = False
    except Exception:
        include_admin = True

    pg = st.navigation(build_streamlit_nav(home, include_admin=include_admin))

    # 侧边栏底部：工作台组件 + 主题切换 + 状态栏
    with st.sidebar:
        st.markdown("---")
        try:
            from core.workspace_ui import render_sidebar_workspace
            render_sidebar_workspace()
        except Exception:
            pass
        render_theme_toggle()
        from core.config import config as _cfg
        from core.llm_presets import get_preset
        mode_label = "深色" if get_color_mode() == "dark" else "浅色"
        _eff = _cfg.effective_llm
        _preset = get_preset(_eff.preset)
        _model_label = _eff.model or _cfg.active_model
        _pname = _preset.label if _preset else _eff.preset
        # 数据源按当前生效配置展示，不再写死
        try:
            from core.data_sources import active_provider
            _src_label = active_provider()
        except Exception:
            _src_label = "eastmoney"
        st.caption(f"{mode_label} · {_pname} · {_model_label} · 数据源 {_src_label} · v2.4")
        if not _cfg.is_configured:
            st.caption("⚠️ 尚未配置 AI 模型 → 前往「账户设置 → 🔌 AI 与数据源」")

    # 每日 AI 验证自动跑批（每自然日一次）
    try:
        from core.evaluation_scheduler import run_daily_evaluation_if_due
        if "daily_eval_bootstrapped" not in st.session_state:
            st.session_state["daily_eval_bootstrapped"] = True
            _eval_res = run_daily_evaluation_if_due()
            if _eval_res:
                st.session_state["daily_eval_result"] = _eval_res
    except Exception:
        pass

    pg.run()
