# 基金智能分析系统 — Release Note V1 / 完整功能手册 + 维护手册

> 版本：**V1（生产就绪版）** · 技术栈：Streamlit（前端）+ FastAPI（API）+ DeepSeek/Anthropic（AI）+ AKShare/东财/Sina（数据）+ SQLite/PostgreSQL（存储）
> 定位：覆盖「宏观研判 → 基金筛选 → Agent 深度分析 → 组合诊断 → 持续监控 → 事后验证」的全链路投资研究平台。
> ⚠️ 本系统仅供学习研究，不构成投资建议。

---

## 目录

- [第一部分：用户使用手册](#第一部分用户使用手册)
  - [1. 整体框架结构](#1-整体框架结构)
  - [2. 完整菜单清单](#2-完整菜单清单8-大分组--33-页)
  - [3. 功能模块清单（core 模块）](#3-功能模块清单core-模块)
  - [4. 功能前后关系（工作流 + 关系图）](#4-功能前后关系工作流--关系图)
  - [5. 页面-能力触达矩阵](#5-页面-能力触达矩阵)
  - [6. 页面布局约定](#6-页面布局约定)
  - [7. API 接口说明](#7-api-接口说明)
  - [8. 数据存储说明](#8-数据存储说明)
- [第二部分：维护手册](#第二部分维护手册)
  - [9. 环境变量维护](#9-环境变量维护)
  - [10. API Key 配置](#10-api-key-配置)
  - [11. 启停服务](#11-启停服务)
  - [12. 数据库维护](#12-数据库维护)
  - [13. 用户与权限维护](#13-用户与权限维护)
  - [14. 定时任务与缓存](#14-定时任务与缓存)
  - [15. 备份与恢复](#15-备份与恢复)
  - [16. 故障排查](#16-故障排查)
  - [17. 生产部署检查清单](#17-生产部署检查清单)
- [附录 A：V1 版本变更摘要](#附录-av1-版本变更摘要)

---

# 第一部分：用户使用手册

## 1. 整体框架结构

系统采用**四层架构**，前端（Streamlit 多页）与 API（FastAPI）共享同一套 `core/` 业务内核。

```mermaid
flowchart TB
    subgraph 交互层
        UI["Streamlit 多页应用<br/>app.py + pages/ (33页)"]
        API["FastAPI 服务<br/>server.py + api/v1/*"]
    end
    subgraph 业务内核 core/
        AICORE["AI/分析引擎<br/>ai_analyzer · model_router · fund_analyzer<br/>intraday_nav · brinson · monte_carlo · strategy_engine"]
        BIZ["业务管理<br/>portfolio · signals · history · alert_engine<br/>track_rebalance · signal_evaluation"]
        SEC["认证/安全<br/>auth · middleware · user_repo"]
        DEC["决策结构化<br/>decision_schema · extractor · renderer"]
    end
    subgraph 数据层 core/
        FETCH["数据采集<br/>data_fetcher · quote_provider · theme_flow<br/>holding_penetration · smart_import"]
        DB["持久化<br/>db (SQLite/PostgreSQL)<br/>persistence (JSON配置)"]
    end
    subgraph 外部依赖
        EXT_DATA["AKShare / 东方财富 / 天天基金 / Sina"]
        EXT_AI["DeepSeek API / Anthropic API"]
    end

    UI --> AICORE & BIZ & SEC & DEC
    API --> AICORE & BIZ & DEC
    AICORE --> EXT_AI
    AICORE --> FETCH
    BIZ --> DB
    SEC --> DB
    FETCH --> EXT_DATA
    FETCH --> DB
```

**关键设计：**
- 前端与 API 复用同一 `core/`，逻辑单点维护。
- 数据源统一封装在 `data_fetcher` / `quote_provider`，带超时、重试、代理处理。
- 存储通过 `DATABASE_URL` 自动切换：未设置 → SQLite 单用户；设置 → PostgreSQL 多用户。
- AI 决策统一输出结构化 JSON（`decision_schema`），可渲染、可导出、可验证。

---

## 2. 完整菜单清单（8 大分组 / 33 页）

侧边栏导航按 8 大分组组织。下表 icon 与 `app.py` 中 `st.navigation` 一致。

### 📋 主页 / 账户
| 页面 | 文件 | icon | 功能 |
|------|------|:---:|------|
| 概要 | `app.py::render_main_page` | 🏠 | 系统首页：Hero、实时指数条、系统概览、三步法工作流、15 个快速入口 |
| 登录/注册 | `pages/00_登录注册.py` | 🔐 | 用户登录/注册；SQLite 模式免登录，PG 模式为认证入口 |
| 账户设置 | `pages/99_账户设置.py` | 👤 | 当前账户信息、Token 用量、退出登录 |
| 用户管理 | `pages/97_用户管理.py` | 👥 | 管理员创建/禁用/改密用户（enterprise 权限） |

### 📈 市场研判
| 页面 | 文件 | icon | 功能 |
|------|------|:---:|------|
| 宏观行业研判 | `pages/01_宏观行业研判.py` | 📈 | 宏观指标（CPI/PPI/PMI）+ 行业景气 AI 研判 |
| 实时市场仪表盘 | `pages/13_实时市场仪表盘.py` | 🖥️ | 指数行情、板块热力图、市场情绪（Sina + 东财） |
| 主题资金流雷达 | `pages/28_主题资金流雷达.py` | 🌊 | 行业/概念主力资金流 → 基金可观察主题；雷达/趋势/观察池/简报 |

### 🔍 基金筛选
| 页面 | 文件 | icon | 功能 |
|------|------|:---:|------|
| 排名精选 Top10 | `pages/10_基金排名精选.py` | 🏆 | 全市场多维打分 → Top 精选 + AI 点评 |
| 债券基金筛选 | `pages/02_债券基金筛选.py` | 📊 | 债基指标过滤 + AI 分析 |
| 指数基金筛选 | `pages/03_指数基金筛选.py` | 📉 | 指数基金/ETF 筛选（费率、跟踪误差、规模） |
| 主动权益筛选 | `pages/04_主动权益筛选.py` | 🎯 | 主动权益多因子筛选 + 经理画像 |
| QDII 基金配置 | `pages/05_QDII基金筛选.py` | 🌍 | QDII 溢价/地域/主题筛选 |

### 🔬 Agent 分析
| 页面 | 文件 | icon | 功能 |
|------|------|:---:|------|
| 单基金深度分析（FAMAS） | `pages/08_FAMAS单基金深度分析.py` | 🔬 | 七 Agent 协作：业绩/经理/持仓/费率/风险/择时/财富顾问 + 决策仪表盘 |
| Brinson 业绩归因 | `pages/25_Brinson业绩归因.py` | 🔬 | 配置/选股/交互效应分解 |
| 专业评级与风格箱 | `pages/17_专业评级与风格箱.py` | 🎓 | 晨星风格箱 + 四机构评级 |
| 新闻情绪分析 | `pages/14_新闻情绪分析.py` | 📰 | 重仓股新闻情绪聚合 |

### 🚨 监控预警
| 页面 | 文件 | icon | 功能 |
|------|------|:---:|------|
| 持续监控预警 | `pages/09_持续监控预警.py` | 🚨 | 自选基金监控列表 + 盘中估值嵌入 |
| 盘中估值中心 | `pages/27_盘中估值中心.py` | 📡 | 重仓穿透 + ETF 联接盘中估值、分时曲线、批量估算 |
| 预警规则配置 | `pages/21_预警规则.py` | 🔔 | 规则类型：净值涨跌、回撤、盘中估值异动、主题资金排名跃变 |
| 通知渠道配置 | `pages/18_通知配置.py` | 📨 | 企业微信/飞书/邮件 Webhook + 降噪 |
| 决策信号跟踪 | `pages/20_信号跟踪.py` | 🚦 | 信号确认/驳回/结果标记（操作层） |

### ⚙️ 组合管理
| 页面 | 文件 | icon | 功能 |
|------|------|:---:|------|
| 资产配置框架 | `pages/06_资产配置框架.py` | 🔧 | 输入画像 → AI 生成股债配比 |
| 组合诊断优化 | `pages/07_组合诊断优化.py` | 🩺 | 集中度/相关性/风格漂移 AI 诊断 |
| 我的组合 | `pages/19_组合管理.py` | 💼 | 组合 CRUD、风险指标、有效前沿、盘中与赛道嵌入 |
| 赛道再平衡对账 | `pages/30_赛道再平衡.py` | ⚖️ | 持仓赛道聚类 → 目标权重 → 再平衡建议 → 一键回写 |

### 🛠️ 常用工具
| 页面 | 文件 | icon | 功能 |
|------|------|:---:|------|
| 基金 PK 擂台 | `pages/11_基金PK擂台.py` | ⚔️ | 多只基金横向对比 |
| 持仓漂移热力图 | `pages/12_持仓漂移热力图.py` | 🔥 | 行业配置随时间漂移可视化 |
| 费率计算器 | `pages/15_费率计算器.py` | 💰 | 申赎/管理费成本测算 |
| 定投回测模拟器 | `pages/16_定投回测模拟器.py` | 📆 | 定投策略历史回测 |
| 导出中心 | `pages/24_导出中心.py` | 📤 | 分析结果导出 Word/PDF/Excel（含决策仪表盘 schema） |

### 📐 量化分析
| 页面 | 文件 | icon | 功能 |
|------|------|:---:|------|
| 蒙特卡洛模拟 | `pages/26_蒙特卡洛模拟.py` | 🎲 | 组合未来路径模拟 + 压力测试 |
| 策略引擎 | `pages/23_策略引擎.py` | 🧩 | YAML 自然语言策略筛选 |
| AI 验证仪表盘 | `pages/29_AI验证仪表盘.py` | 🎯 | T+1/3/5/10/20 多窗口验证、方向准确率、Brier、校准曲线（统计层） |
| 分析历史 | `pages/22_分析历史.py` | 📚 | 历史分析回放、结构化仪表盘、T+N 验证结果 |

---

## 3. 功能模块清单（core 模块）

`core/` 共 44 个模块，按职责分类：

### 数据采集层
| 模块 | 职责 |
|------|------|
| `data_fetcher.py` | 基金列表/净值/持仓/估值/宏观/指数估值（AKShare + 天天基金 + 东财），带超时/重试/缓存 |
| `quote_provider.py` | Sina 实时行情（个股/ETF/指数），统一绕代理与编码 |
| `theme_flow.py` | 行业/概念主力资金流拉取（AKShare 主 + 东财兜底）、快照、排名跃变检测 |
| `theme_taxonomy.py` | 板块 → 基金主题归并规则（`data/theme_taxonomy.yaml` 驱动） |
| `theme_brief.py` | 主题观察简报（Markdown）生成 |
| `stock_sectors.py` | 股票 → 申万行业映射 |
| `holding_penetration.py` | 基金持仓穿透行业暴露计算 |
| `etf_linkage_map.py` | 联接基金 → 场内 ETF 映射（`data/etf_linkage_map.json`） |
| `market_phase.py` | 市场阶段/估值分位判断 |
| `smart_import.py` | 持仓/自选智能导入（CSV/Excel/文本） |

### AI / 分析引擎
| 模块 | 职责 |
|------|------|
| `ai_analyzer.py` | 多后端 AI 引擎（DeepSeek/Anthropic），流式/非流式；**按 session/请求隔离** |
| `model_router.py` | 多模型路由、断路器、降级 |
| `prompt_templates.py` | 提示词模板加载（`prompts/*.yaml`/`*.md`） |
| `fund_analyzer.py` | 基金综合指标与评分 |
| `intraday_nav.py` | 盘中估值引擎（重仓穿透 / ETF 联接 / 官方回退）+ 分时快照 |
| `brinson.py` | Brinson 业绩归因 |
| `monte_carlo.py` | 蒙特卡洛路径模拟 |
| `portfolio_optimizer.py` | 组合优化（风险平价/最大夏普/有效前沿） |
| `strategy_engine.py` | YAML 策略引擎 |
| `track_rebalance.py` | 赛道聚类 + 目标权重 + 再平衡对账（可叠加资金热度） |
| `calibration_metrics.py` | Brier / ECE / 分桶校准 |
| `signal_evaluation.py` | 信号多窗口 T+N 验证引擎 |
| `agent_memory.py` | Agent 记忆 + 信号自动评判 |
| `decision_schema.py` / `decision_extractor.py` / `decision_renderer.py` | 决策仪表盘 JSON schema / 提取 / 渲染 |

### 业务管理 / 持久化
| 模块 | 职责 |
|------|------|
| `db.py` | 数据库层（SQLite/PostgreSQL 双模式）、schema、`get_user_id` |
| `portfolio.py` | 组合与持仓管理 |
| `signals.py` | 决策信号 CRUD |
| `history.py` | 分析历史（含 `structured_result_json`） |
| `alert_engine.py` | 预警规则引擎与巡检 |
| `notifications.py` / `notification_noise.py` | 通知渠道 + 降噪 |
| `persistence.py` | 通用 JSON 配置持久化 |
| `user_repo.py` | 用户数据仓储 |
| `evaluation_scheduler.py` | 每日验证自动跑批调度 |

### 认证 / 安全
| 模块 | 职责 |
|------|------|
| `auth.py` | 密码哈希（bcrypt）+ JWT 签发/验证 |
| `middleware.py` | 页面认证守卫 `require_auth` + 配额 `check_quota` |

### UI / 导出 / 基础
| 模块 | 职责 |
|------|------|
| `ui_components.py` | 统一 UI 组件（页头、侧栏、工具栏、表格、决策仪表盘渲染、认证守卫接入） |
| `common.py` | 通用导出辅助 |
| `report_renderer.py` | 报告渲染 |
| `export.py` | Word/PDF/Excel 导出（含决策 schema 卡片区） |
| `config.py` | 全局配置（环境变量加载、AI 提供商检测） |
| `utils.py` | 工具函数（缓存、安全转换、并发） |
| `__init__.py` | 包初始化（macOS WeasyPrint 库路径注入） |

---

## 4. 功能前后关系（工作流 + 关系图）

### 4.1 推荐工作流：漏斗式三步法

```mermaid
flowchart LR
    A["① 定框架<br/>06 资产配置"] --> B["② 填标的<br/>10/02/03/04/05 筛选<br/>08 FAMAS 深度分析"]
    B --> C["③ 做体检<br/>07 组合诊断<br/>19 我的组合<br/>30 赛道再平衡"]
    C --> D["④ 持续监控<br/>09 监控 · 27 盘中估值<br/>21 预警 · 18 通知"]
    D --> E["⑤ 事后验证<br/>20 信号跟踪 → 29 AI验证<br/>22 分析历史"]
    E -.反馈优化.-> B
```

### 4.2 决策 JSON 横切数据流

```mermaid
flowchart LR
    AI["AI 流式分析<br/>ui_components.run_analysis_stream"]
    EX["decision_extractor<br/>提取结构化 JSON"]
    RE["decision_renderer<br/>卡片渲染"]
    HIST["22 分析历史<br/>structured_result_json"]
    SIG["20 信号池<br/>signal_for_validation"]
    EVA["29 AI 验证仪表盘"]
    EXP["24 导出中心<br/>Word/PDF schema"]
    API["API GET /history/{id}/dashboard"]

    AI --> EX --> RE
    EX --> HIST
    EX --> SIG --> EVA
    HIST --> EXP
    HIST --> API
```

### 4.3 监控/资金/估值联动

```mermaid
flowchart TB
    P27["27 盘中估值中心"] --> P09["09 持续监控"]
    P27 --> P19["19 我的组合"]
    P28["28 主题资金流雷达"] --> P01["01 宏观研判"]
    P28 --> P30["30 赛道再平衡"]
    P21["21 预警规则"] -->|盘中估值异动| P27
    P21 -->|主题资金排名跃变| P28
    P09 --> P18["18 通知渠道"]
```

---

## 5. 页面-能力触达矩阵

| 页面 \ 能力 | 盘中估值 | 主题资金 | AI验证 | 决策JSON | 赛道再平衡 | 导出 |
|-------------|:---:|:---:|:---:|:---:|:---:|:---:|
| 01 宏观 | | ●入口 | | ● | | ● |
| 06 资产配置 | | | | ● | ●输入 | ● |
| 07 组合诊断 | | | ● | ● | ● | ● |
| 08 FAMAS | ●嵌入 | | ● | ●主战场 | | ● |
| 09 监控 | ●嵌入 | | | | | |
| 10 排名精选 | | | | ● | | ● |
| 19 组合管理 | ●组合涨跌 | | | | ●数据源 | |
| 20 信号跟踪 | | | ●操作层 | ●来源 | | |
| 21 预警规则 | ●新规则 | ●新规则 | | | | |
| 22 分析历史 | | | ●回放 | ●存储 | | ● |
| 27 盘中估值 ★ | ●主页面 | | | | | ● |
| 28 主题资金 ★ | | ●主页面 | | | ●景气 | ● |
| 29 AI验证 ★ | | | ●主页面 | ●依赖 | | |
| 30 赛道再平衡 ★ | | ●景气 | | | ●主页面 | |

---

## 6. 页面布局约定

统一由 `core/ui_components.py` 提供，所有功能页遵循同一结构：

```
┌─────────────────────────────────────────────┐
│ render_page_header(title, icon, desc, help)   │  ← 顶部标题卡（含认证守卫）
│   └ 左侧色块 + 标题 + 描述 + 💡使用说明折叠     │
├─────────────────────────────────────────────┤
│ render_top_toolbar()                          │  ← 数据刷新时间 + 全局缓存刷新
│ 侧栏 render_sidebar_config()                  │  ← 基金速查 + AI 模型/深度
├─────────────────────────────────────────────┤
│ 主内容区：                                     │
│   - 参数控件（columns / expander）            │
│   - primary 触发按钮（+ spinner 加载态）       │
│   - 结果区：指标行 / show_sortable_df / Plotly │
│   - 底部 page_link 工作流引导                  │
└─────────────────────────────────────────────┘
```

**关键组件：**
- `render_page_header` — 统一页头，**内置 `require_auth()` 认证守卫**。
- `render_sidebar_config` / `render_top_toolbar` — 侧栏与工具栏。
- `show_sortable_df` — 可排序表格（百分比自动格式化）。
- `render_intraday_nav` — 盘中估值卡片（08/19/27 复用）。
- `render_decision_dashboard` — 决策仪表盘卡片（分析页 + 历史回放）。
- `run_analysis_stream` — AI 流式输出 + 自动解析/渲染/存储决策 JSON。

---

## 7. API 接口说明

**基础地址：** `http://<host>:8502`
**鉴权：** 除根路径 `/` 外，所有 `/api/v1/*` 需请求头 `X-API-Key: <API_ACCESS_KEY>`。未配置 `API_ACCESS_KEY` 时全部返回 503。
**交互文档：** `/docs`（Swagger）、`/redoc`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务状态（免鉴权，供探活） |
| GET | `/api/v1/health` · `/health/ready` | 健康检查 |
| GET | `/api/v1/funds/search` | 基金搜索 |
| GET | `/api/v1/funds/{code}/nav` | 历史净值 |
| GET | `/api/v1/funds/{code}/info` | 基金概况 |
| GET | `/api/v1/funds/{code}/estimate` | 盘中估值 |
| GET | `/api/v1/funds/{code}/holdings` | 前十大持仓 |
| GET | `/api/v1/funds/{code}/comprehensive` | 综合数据 |
| GET | `/api/v1/funds/screen/list` | 基金筛选 |
| GET | `/api/v1/funds/macro` | 宏观指标 |
| POST | `/api/v1/analysis/run` | 执行 AI 分析（`structured=true` 返回决策 JSON 双格式） |
| GET | `/api/v1/analysis/templates` | 分析模板列表 |
| POST | `/api/v1/analysis/chat` | 快速问答 |
| GET | `/api/v1/history/` · `/{id}` · `/{id}/dashboard` | 分析历史查询 / 结构化仪表盘 |
| DELETE | `/api/v1/history/{id}` | 删除历史 |
| GET | `/api/v1/history/compare/funds` · `/fund/{code}` | 历史对比 / 按基金 |
| POST | `/api/v1/portfolio/` · GET `/` · `/{id}` | 组合 CRUD |
| DELETE | `/api/v1/portfolio/{id}` | 删除组合 |
| POST/DELETE | `/api/v1/portfolio/{id}/holdings[...]` | 持仓增删 |
| GET | `/api/v1/portfolio/{id}/risk` · `/nav` | 组合风险 / 净值 |
| GET | `/api/v1/alerts/rules` · POST · DELETE · PUT `/{id}/toggle` | 预警规则管理 |
| GET | `/api/v1/alerts/triggers` · POST `/{id}/acknowledge` · `/evaluate` | 触发记录 / 确认 / 巡检 |
| GET | `/api/v1/signals/` · `/stats` | 信号列表 / 统计 |
| POST | `/api/v1/evaluation/run` · GET `/summary` `/calibration` `/items` `/pending` | AI 验证跑批与统计 |
| GET | `/api/v1/export/analysis/{id}` · `/fund/{code}` | 结果导出 |

**调用示例：**
```bash
curl -H "X-API-Key: $API_ACCESS_KEY" \
     "http://localhost:8502/api/v1/funds/000001/comprehensive"
```

---

## 8. 数据存储说明

| 位置 | 内容 |
|------|------|
| `data/fund_analysis.db` | SQLite 主库（单用户模式）：users/portfolios/signals/analysis_history/alerts/signal_evaluations 等 |
| PostgreSQL（`DATABASE_URL`） | 多用户模式主库，表结构同上，按 `user_id` 隔离 |
| `data/etf_linkage_map.json` | ETF 联接映射（可人工维护） |
| `data/theme_taxonomy.yaml` | 主题归并规则（可人工维护） |
| `data/theme_flow_snapshots/` | 主题资金流每日快照 CSV |
| `data/theme_flow_rank_cache.json` | 主题资金排名缓存（跃变检测用） |
| `data/intraday_snapshots/{code}/{date}.csv` | 盘中估值分时快照 |
| `data/notification_config.json` | 通知渠道配置（含 Webhook/SMTP，**含敏感信息**） |
| `data/evaluation_last_run.txt` | 每日验证跑批日期标记 |
| `data/.jwt_secret` | 自动生成的 JWT 密钥（未设 `JWT_SECRET` 时） |
| `prompts/` | 27 个提示词模板（YAML + Markdown） |
| `strategies/` | YAML 策略定义 |

---

# 第二部分：维护手册

## 9. 环境变量维护

配置文件：项目根目录 `.env`（模板见 `.env.example`）。修改后需**重启服务**生效。

| 变量 | 必需 | 默认 | 说明 |
|------|:---:|------|------|
| `DEEPSEEK_API_KEY` | AI 必需 | 空 | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | 否 | `https://api.deepseek.com` | DeepSeek 接口地址 |
| `DEEPSEEK_MODEL` | 否 | `deepseek-v4-flash` | 默认模型（flash 快 / pro 深度） |
| `AI_PROVIDER` | 否 | 自动检测 | `deepseek` 或 `anthropic` |
| `ANTHROPIC_API_KEY` | 备用 | 空 | Claude API 密钥 |
| `ANTHROPIC_MODEL` | 否 | `claude-sonnet-4-6` | Claude 模型 |
| `TUSHARE_TOKEN` | 否 | 空 | Tushare 备选数据源 |
| `STREAMLIT_SERVER_PORT` | 否 | `8501` | 前端端口 |
| `DATABASE_URL` | 多用户必需 | 空 | 设置后启用 PostgreSQL 多用户；不设为 SQLite |
| `ADMIN_DEFAULT_PASSWORD` | 生产建议 | 空 | 多用户模式初始化管理员密码；**未设则不建管理员** |
| `JWT_SECRET` | 生产建议 | 自动生成 | 会话签名密钥；多实例需统一设置 |
| `JWT_EXPIRY_HOURS` | 否 | `24` | 登录态有效期（小时） |
| `API_ACCESS_KEY` | API 必需 | 空 | FastAPI 访问密钥；**未设则 API 全拒绝(503)** |
| `CORS_ALLOW_ORIGINS` | 否 | 空 | 允许跨域来源（逗号分隔），默认不允许跨域 |
| `DISABLE_SSL_VERIFY` | 否 | 关闭 | 设 `1` 关闭 SSL 校验（仅本地证书链不全时临时用，**生产禁用**） |

**生产环境最小安全配置示例（`.env`）：**
```env
DEEPSEEK_API_KEY=sk-xxxxxxxx
DATABASE_URL=postgresql://user:pass@host:5432/fund
ADMIN_DEFAULT_PASSWORD=<强密码>
JWT_SECRET=<64位随机串>
API_ACCESS_KEY=<64位随机串>
CORS_ALLOW_ORIGINS=https://your-frontend.example.com
# DISABLE_SSL_VERIFY 保持不设置（默认开启校验）
```

生成随机密钥：
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 10. API Key 配置

### AI 提供商 Key（DeepSeek，默认）
1. 访问 https://platform.deepseek.com/api_keys 获取。
2. 写入 `.env` 的 `DEEPSEEK_API_KEY`。
3. 重启 Streamlit；在任意分析页侧栏可切换 `deepseek-v4-flash` / `deepseek-v4-pro`。
4. 校验：账户设置页可见脱敏 Key（`sk-xxxx...xxxx`），或 `config.is_configured` 为真。

### FastAPI 访问 Key
- 设置 `API_ACCESS_KEY`，客户端每次请求带 `X-API-Key`。
- 未设置时 `/api/v1/*` 返回 503（secure-by-default，不会静默开放）。
- 轮换：更新 `.env` 后重启 API 服务，并同步更新调用方。

---

## 11. 启停服务

系统由两个独立进程组成，可分别启停。

### 前端（Streamlit）
```bash
# 本地
streamlit run app.py

# 局域网/生产（指定地址与端口）
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```
访问：`http://<host>:8501`

### API（FastAPI）
```bash
# 开发（自动重载）
python server.py

# 生产（uvicorn，多进程见下方注意）
uvicorn server:app --host 0.0.0.0 --port 8502
```
访问：`http://<host>:8502/docs`

### 停止
- 前台运行：`Ctrl + C`。
- 后台运行：`pkill -f "streamlit run app.py"` / `pkill -f "server:app"`。

### 生产托管建议（示例）
```bash
# 用 nohup 后台常驻
nohup streamlit run app.py --server.address 0.0.0.0 --server.port 8501 > logs/streamlit.log 2>&1 &
nohup uvicorn server:app --host 0.0.0.0 --port 8502 > logs/api.log 2>&1 &
```

> ⚠️ **重要**：修改 `core/` 或 `.env` 后必须重启进程——Python 模块与环境变量在旧进程内不会热重载。

> ⚠️ **多 worker 注意**：`evaluation_scheduler` 每日跑批基于文件标记、无分布式锁；如用多进程/多副本部署，建议仅在单一实例启用自动跑批，或改由外部 cron 触发 `POST /api/v1/evaluation/run`，避免重复执行。

---

## 12. 数据库维护

### 模式切换
- **SQLite（默认）**：不设 `DATABASE_URL`，数据在 `data/fund_analysis.db`，适合单机自用。
- **PostgreSQL（多用户）**：设 `DATABASE_URL=postgresql://user:pass@host:port/db`。

> 注意：若 `DATABASE_URL` 已配置但 PostgreSQL 连接失败，**不会再降级到 SQLite**，应用直接启动失败并抛出 `RuntimeError`。生产请保证 `fund-pg` 健康、compose 网络可达后再启动 `fund-app`。本地单用户可注释/清空 `DATABASE_URL` 使用 SQLite。

### 表结构
- 首次导入 `core.db` 时自动 `init_db()` 建表 + `ensure_schema()` 增量迁移。
- 迁移为幂等的「缺表/缺列即补」，无版本号；升级前建议先备份。

### 常用运维查询（PostgreSQL）
```sql
-- 用户列表
SELECT id, email, tier, is_active, last_login_at FROM users ORDER BY id;
-- 某用户组合数
SELECT user_id, count(*) FROM portfolios GROUP BY user_id;
-- 验证样本量
SELECT horizon_days, count(*) FROM signal_evaluations GROUP BY horizon_days;
```

### 连接信息
- SQLite：`data/fund_analysis.db`（直接文件）。
- PostgreSQL：连接池 2–15，连接串仅存于 `.env`，不落日志。

---

## 13. 用户与权限维护

### 权限模型
- `tier` 决定配额与权限：`free` / `pro` / `enterprise`。
- `enterprise` 即管理员（可访问「用户管理」页）。

### 管理员账户
- 多用户模式首次初始化时，若设了 `ADMIN_DEFAULT_PASSWORD` 则创建 `admin@fund.local`；未设则不创建。
- **遗留弱口令处理**：早期版本会创建 `admin@fund.local / admin123`。升级后请务必改密或禁用：

```sql
-- 禁用遗留管理员
UPDATE users SET is_active = 0 WHERE email = 'admin@fund.local';
```
或在「用户管理」页操作。

### 常用操作
- 新增用户：登录页「注册」或管理员在「用户管理」创建。
- 改密/禁用：「用户管理」页（enterprise 权限）。
- 单用户模式（SQLite）：自动使用 `local@fund.local`，免登录。

### 认证守卫行为
- `render_page_header` 内置 `require_auth()`：SQLite 自动登录本地用户；PG 未登录跳登录页。
- 所有功能页因调用页头而自动受守卫保护。

---

## 14. 定时任务与缓存

### 每日 AI 验证跑批
- 触发点：`app.py` 启动首个 session 时调用 `run_daily_evaluation_if_due()`，每自然日一次。
- 标记文件：`data/evaluation_last_run.txt`。
- 手动触发：29 页「立即运行验证任务」按钮，或 API `POST /api/v1/evaluation/run`。

### 缓存
- 数据层 `@timed_cache`：进程内缓存，TTL 300s–1 天。
- 全局刷新：任意页顶部工具栏「刷新」按钮 → `st.cache_data.clear()`。
- 主题资金/盘中估值快照落盘，供趋势与分时曲线累积。

---

## 15. 备份与恢复

### 需备份的内容
```
data/fund_analysis.db          # SQLite 主库（或 pg_dump 导出 PG）
data/*.json  data/*.yaml       # 映射/主题/通知配置
data/theme_flow_snapshots/     # 资金流历史快照
data/intraday_snapshots/       # 盘中分时快照
.env                           # 配置与密钥（妥善保管，勿入库）
prompts/  strategies/          # 模板与策略
```

### 备份示例
```bash
# SQLite
cp data/fund_analysis.db backups/fund_$(date +%F).db
# PostgreSQL
pg_dump "$DATABASE_URL" > backups/fund_$(date +%F).sql
# 配置与数据目录打包
tar czf backups/data_$(date +%F).tgz data/ .env prompts/ strategies/
```

### 恢复
- SQLite：还原 `.db` 文件后重启。
- PostgreSQL：`psql "$DATABASE_URL" < backups/xxx.sql`。

---

## 16. 故障排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 页面提示 API Key 未配置 | 未设 `DEEPSEEK_API_KEY` | 填入 `.env` 并重启 |
| `/api/v1/*` 全部 503 | 未设 `API_ACCESS_KEY` | 设置后重启 API |
| API 返回 401 | 缺 `X-API-Key` 或不匹配 | 检查请求头与密钥 |
| PG 未生效、数据写本地 | 旧版静默降级遗留问题；现已禁止降级 | 确认 `DB_MODE=postgresql`；检查 `fund-pg` 健康与 compose 网络 |
| PDF 导出失败（libgobject 等） | 缺 Pango/Cairo 系统库 | macOS `brew install pango`；Linux `apt install libpango-1.0-0 libpangocairo-1.0-0` |
| 主题资金流为空 | 数据源限流/断网 | 点「刷新」重试；AKShare 失败会自动降级东财 |
| 实时行情不可用 | 交易时段外或源站限流 | 非交易时段返回最后价；稍后重试 |
| SSL 证书错误 | 本地证书链不全 | 临时设 `DISABLE_SSL_VERIFY=1`（生产勿用） |
| 多用户看不到自己的验证数据 | 自动跑批仅覆盖当前上下文用户 | 各用户可在 29 页手动「立即运行」 |
| `database is locked` | SQLite 多用户并发写 | 改用 PostgreSQL 多用户模式 |
| 改了代码/配置不生效 | 进程未重启 | 重启 Streamlit / API 进程 |

---

## 17. 生产部署检查清单

上线前逐项确认：

- [ ] `.env` 已配置：`DEEPSEEK_API_KEY`、`DATABASE_URL`、`ADMIN_DEFAULT_PASSWORD`、`JWT_SECRET`、`API_ACCESS_KEY`
- [ ] `CORS_ALLOW_ORIGINS` 按前端域名收紧（或留空禁跨域）
- [ ] `DISABLE_SSL_VERIFY` 未设置（默认开启证书校验）
- [ ] 遗留 `admin@fund.local / admin123` 已改密或禁用
- [ ] PostgreSQL 连接成功（启动时 `from core.db import DB_MODE` 为 `postgresql`，无 RuntimeError）
- [ ] 已装系统库：Node.js（AKShare）、Pango/Cairo（PDF）
- [ ] 自动跑批仅在单实例启用，或改用外部 cron 调 API
- [ ] `data/` 与数据库已纳入定期备份
- [ ] `.env`、`data/notification_config.json`、`data/.jwt_secret` 不对外暴露、不入版本库
- [ ] 前端 8501 / API 8502 端口的访问范围（防火墙/反向代理）已控制

---

# 附录 A：V1 版本变更摘要

相对早期版本，V1 主要新增与加固：

### 新增功能
- **盘中估值中心（27）**：重仓穿透 + ETF 联接盘中估值 + 分时快照。
- **主题资金流雷达（28）**：行业/概念资金流 → 基金主题归并 + 趋势 + 观察简报。
- **AI 验证仪表盘（29）**：T+1/3/5/10/20 多窗口验证 + Brier + 校准曲线。
- **赛道再平衡对账（30）**：持仓赛道聚类 + 目标权重 + 一键回写（可叠加资金热度）。
- **结构化决策仪表盘 JSON**：分析流横切，贯通历史/信号/验证/导出/API。
- 预警新增类型：盘中估值异动、主题资金排名跃变。
- 每日 AI 验证自动跑批。

### 生产安全加固
- **FastAPI 鉴权**：`/api/v1/*` 需 `X-API-Key`；CORS 由 `CORS_ALLOW_ORIGINS` 控制。
- **Streamlit 认证守卫**：`render_page_header` 内置 `require_auth`，PG 多用户强制登录、SQLite 免登录。
- **默认管理员改造**：密码取自 `ADMIN_DEFAULT_PASSWORD`，未设不创建弱口令账户。
- **SSL 校验默认开启**：仅 `DISABLE_SSL_VERIFY=1` 时关闭。
- **AI 实例隔离**：Streamlit 按 session、FastAPI 按请求，消除多用户串模型。

### UI 优化
- 首页快速入口补全为 15 项（3×5）。
- 系统概览页面数校正为 30。
- 侧栏 📡 图标去重（13→🖥️、20→🚦、27 保留 📡）。

---

# 附录 B：数据源清单与详情

系统所用数据全部来自公开第三方接口，按用途分为 **AI 推理**、**基金基础数据**、**行情/板块**、**宏观/估值**、**新闻** 五类。下表列出全部数据源、接入方式、涉及模块与备注。

## B.1 AI 推理数据源

| 数据源 | 接入地址/方式 | 用途 | 涉及模块 | 备注 |
|--------|--------------|------|----------|------|
| **DeepSeek API** | `https://api.deepseek.com`（OpenAI 兼容 SDK） | 全部 AI 分析（默认引擎） | `ai_analyzer.py` · `model_router.py` | 需 `DEEPSEEK_API_KEY`；模型 `deepseek-v4-flash`/`deepseek-v4-pro` |
| **Anthropic Claude API** | `https://api.anthropic.com`（anthropic SDK） | AI 分析（备用引擎） | `ai_analyzer.py` | 需 `ANTHROPIC_API_KEY`；默认 `claude-sonnet-4-6` |

## B.2 基金基础数据源

| 数据源 | 接入地址/接口 | 用途 | 涉及模块 | 备注 |
|--------|--------------|------|----------|------|
| **天天基金（直连 HTTP）** | `http://fund.eastmoney.com/pingzhongdata/{code}.js` | 基金详情、单位/累计净值走势 | `data_fetcher.py::_parse_fund_detail_js` | 明文 HTTP；解析 JS 变量 |
| **天天基金 估值（直连）** | `http://fundgz.1234567.com.cn/js/{code}.js` | 盘中实时估算净值 | `data_fetcher.py::get_realtime_estimate` | 仅交易时段有效 |
| **天天基金 基金列表（直连）** | `http://fund.eastmoney.com/js/fundcode_search.js` | 全市场基金代码/简称检索 | `data_fetcher.py` | 全量列表，本地缓存 |
| **AKShare `fund_open_fund_info_em`** | 东方财富封装 | 历史净值序列 | `data_fetcher.py::get_fund_nav_history` | 净值主通道 |
| **AKShare `fund_open_fund_rank_em`** | 东方财富封装 | 开放式基金排名 | `pages/10_基金排名精选.py` | — |
| **AKShare `fund_portfolio_hold_em`** | 东方财富封装 | 基金前十大持仓 | `data_fetcher.py` · `brinson.py` · `pages/12` | 季报披露，存在滞后 |
| **AKShare `fund_hold_structure_em`** | 东方财富封装 | 持有人结构 | `data_fetcher.py` | — |
| **AKShare `fund_announcement_personnel_em`** | 东方财富封装 | 基金经理变更公告 | `data_fetcher.py` | — |
| **AKShare `fund_rating` / `fund_rating_all`** | 东财/评级机构封装 | 基金评级（含晨星等） | `data_fetcher.py` · `fund_analyzer.py` | 全量拉取，注意限流 |
| **Tushare Pro `fund_portfolio`** | `https://tushare.pro`（需 token） | 基金持仓（备选） | `data_fetcher.py` | 需 `TUSHARE_TOKEN`，可选 |

## B.3 行情 / 板块数据源

| 数据源 | 接入地址/接口 | 用途 | 涉及模块 | 备注 |
|--------|--------------|------|----------|------|
| **新浪财经 行情** | `https://hq.sinajs.cn/list=...` | 指数/个股/ETF 实时行情 | `quote_provider.py` · `app.py` · `pages/13` | 绕系统代理、gb2312 编码；盘中估值穿透用 |
| **AKShare `stock_sector_spot`（新浪）** | 新浪行业板块封装 | 行业板块涨跌热力图 | `quote_provider.py::get_sector_board` · `pages/13` | 东财 push2 常被反爬，故改用新浪源 |
| **东方财富 K线** | `https://push2his.eastmoney.com/api/qt/stock/kline/get` | 个股日 K 线（备选） | `data_fetcher.py` | efinance 不可用时的备选 |
| **efinance** | `ef.stock.get_quote_history`（Python 库） | 个股/指数日 K 线（主通道） | `data_fetcher.py` · `brinson.py` · `market_phase.py` | 代理兼容性好，稳定 |
| **AKShare `stock_fund_flow_industry` / `_concept`（同花顺）** | 同花顺 `data.10jqka.com.cn` 封装 | 行业/概念主力资金流 | `theme_flow.py` | 主题资金雷达主通道 |
| **东方财富 push2 clist** | `https://push2.eastmoney.com/api/qt/clist/get` | 板块资金流（同花顺失败时兜底）、持仓行业辅助 | `theme_flow.py` · `holding_penetration.py` | 该端点对部分网络会主动断连（反爬） |
| **AKShare `stock_individual_info_em`** | 东方财富封装 | 个股基础信息（行业归属） | `fund_analyzer.py` | 持仓穿透用 |

## B.4 宏观 / 估值数据源

| 数据源 | 接入地址/接口 | 用途 | 涉及模块 | 备注 |
|--------|--------------|------|----------|------|
| **AKShare `macro_china_*`** | 国家统计局/东财封装 | CPI/PPI/PMI/货币供应/LPR/GDP | `data_fetcher.py::get_macro_data` | 宏观研判用 |
| **AKShare `stock_index_pe_lg` / `stock_index_pb_lg`（乐股）** | `legulegu` 封装 | 指数 PE/PB 历史分位 | `data_fetcher.py::get_index_valuation` | 估值红绿灯用 |
| **AKShare `stock_zh_index_value_csindex`（中证指数）** | 中证指数官网封装 | 中证系列指数估值 | `data_fetcher.py` | 指数估值补充 |
| **Tushare Pro 宏观接口** | `https://tushare.pro`（需 token） | 宏观指标（备选） | `data_fetcher.py::get_macro_data` | 可选备选 |

## B.5 新闻数据源

| 数据源 | 接入地址/接口 | 用途 | 涉及模块 | 备注 |
|--------|--------------|------|----------|------|
| **AKShare `stock_news_em`** | 东方财富封装 | 重仓股相关新闻 | `pages/14_新闻情绪分析.py` | 情绪分析输入 |

## B.6 主备关系与降级策略

- **个股 K 线**：efinance（主） → 东财 push2his kline（备）。
- **基金持仓/宏观**：AKShare（主） → Tushare（备，需 token）。
- **主题/板块资金流**：AKShare 同花顺（主） → 东财 push2 clist（兜底）。
- **行业板块热力图**：AKShare 新浪 `stock_sector_spot`（东财 push2 反爬，已弃用直连）。
- **HTTP 统一封装**：`data_fetcher._http_get` 带超时（默认 15s）、重试（最多 3 次）、系统代理→直连兜底；新浪与东财 push2 走绕代理直连。

## B.7 数据时效与使用注意

| 事项 | 说明 |
|------|------|
| 实时行情/估值 | 仅交易时段有效；非交易时段返回最后收盘价 |
| 基金持仓 | 来自季报披露，存在 1 个季度左右滞后；盘中穿透估值置信度据此标注 high/medium/low |
| 净值 | T 日净值通常当晚更新；FOF 等披露更慢 |
| 限流 | 东财/AKShare/同花顺源在高频调用时可能限流或断连，系统以重试 + 进程内缓存（TTL 300s–1 天）缓解 |
| 代理 | 企业代理环境下东财 push2 易失败；新浪、天天基金直连通常正常 |
| SSL | 默认开启证书校验；仅在本地证书链不全时用 `DISABLE_SSL_VERIFY=1` 临时绕过 |
| 合规 | 所有数据源均为公开第三方接口，源站改版可能导致短期失效；数据仅供研究，不构成投资建议 |

> 说明：通知渠道（企业微信/飞书/邮件 Webhook）为**出站推送**，非数据获取源，配置见 `18 通知渠道配置` 与 `data/notification_config.json`。

---

*文档版本：V1 · 生成于 2026-07-09 · 本系统仅供学习研究，不构成投资建议。*
