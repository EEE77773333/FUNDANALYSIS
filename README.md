<div align="center">

# 🏦 基金智能分析系统

**把 AI 拉进你的基金投研流程 —— 从宏观研判到组合诊断的完整闭环**

开源 · 可自部署 · 自带模型密钥（BYOK）· 数据源可切换 · 无使用次数限制

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.44%2B-FF4B4B.svg)](https://streamlit.io/)

</div>

---

## 这是什么

一个跑在浏览器里的 **中国公募基金分析工作台**，34 个功能页面覆盖：

> 今日看板 → 选基筛选 → AI 深度分析 → 组合诊断 → 持续监控预警 → 量化工具
> ![Uploading image.png…]()


技术上它是一套 **Streamlit + 大语言模型 + 公开行情源** 的应用。你可以：

- 用**自己的**大模型 API Key（DeepSeek / 通义 / 智谱 / Kimi / OpenAI / 本地 Ollama 都行）
- 用**自己的**行情数据源（东财 / AKShare / Tushare / Baostock 可切换）
- 部署在**自己的**电脑或服务器上，数据不出本机

**没有次数限制**：成本由你自己的模型 key 承担。

> 📸 **功能演示**
>
> 建议在这里放 3~5 张截图或一段 30 秒 GIF（工作台 / FAMAS 深度分析 / 组合诊断 / 监控预警）。
> 保存到 `docs/images/` 后替换本段。

---

## 为什么用它

| 常见做法 | 本项目 |
|---|---|
| 盯着十几个网页手动翻基金数据 | 一个工作台把行情、估值、宏观、持仓串起来 |
| 用通用大模型问基金，它不知道你的持仓 | 把真实数据和指标喂给模型，按专业框架输出 |
| 免费工具只能看，不能算 | 内置夏普/回撤/Brinson 归因/蒙特卡洛等量化能力 |
| SaaS 按次收费，用着心疼 | 自部署 + 自带 key，用多少算多少 |
| 数据源被限流就瘫痪 | 多源自动降级 + 本地缓存，主源挂了自动切备用 |

---

## 功能矩阵

### 📊 今日看板
| 页面 | 说明 |
|---|---|
| 工作台 | 个人化首页：自选基金、快捷入口、最近分析 |
| 市场仪表盘 | 实时指数、涨跌分布、资金流向一屏掌握 |
| 主题资金流雷达 | 主题/板块资金异动追踪 |
| 盘中估值中心 | 基金盘中实时估值与溢价监控 |

### 🔍 选基
| 页面 | 说明 |
|---|---|
| 宏观行业研判 | CPI/PPI/PMI 等宏观指标 + AI 行业解读 |
| 基金排名精选 | 全市场多维度排名与榜单 |
| 主动权益筛选 | 夏普、最大回撤、超额收益等指标筛选 |
| 指数基金筛选 | 跟踪误差、规模、费率多维过滤 |
| 债券基金筛选 | 久期、信用、回撤视角筛选债基 |
| QDII 配置 | 跨境资产配置与海外指数估值 |
| 基金 PK | 多只基金指标横向对比 |
| 评级与风格箱 | 九宫格风格箱 + 专业评级 |

### 🔬 深度分析
| 页面 | 说明 |
|---|---|
| **FAMAS 深度分析** | 多 Agent 协作：招募书 / 业绩 / 费率 / 经理 / 持仓 / 宏观 / 综合，逐层推导 |
| 新闻情绪分析 | 抓取基金相关资讯，AI 判断情绪倾向 |
| Brinson 业绩归因 | 拆解超额收益来自行业配置还是个股选择 |

### 💼 持仓组合
| 页面 | 说明 |
|---|---|
| 我的组合 | 录入持仓，跟踪组合净值曲线 |
| 组合诊断 | AI 诊断集中度、风格漂移、费率效率并给调仓建议 |
| 资产配置框架 | 按风险承受力生成股债配比方案 |
| 持仓漂移热力图 | 行业与风格漂移可视化 |
| 赛道再平衡 | 赛道偏离度计算与再平衡建议 |

### 🚨 监控预警
| 页面 | 说明 |
|---|---|
| 持续监控 | 常驻盯盘，触发条件自动记录 |
| 预警规则 | 自定义涨跌幅、回撤、估值分位等触发条件 |
| 信号跟踪 | 历史信号复盘与命中率统计 |
| 通知配置 | 飞书 / 邮件等通道推送 |

### 🧰 工具与量化
| 页面 | 说明 |
|---|---|
| 费率计算器 | 申购/赎回/管理费全成本测算 |
| 定投回测 | 历史定投方案收益回测 |
| 策略引擎 | 组合策略定义与执行 |
| 蒙特卡洛模拟 | 未来收益分布概率模拟 |
| AI 验证 | 追踪 AI 判断的实际命中率（Brier 分数） |
| 导出中心 / 分析历史 / 分享阅读 | 报告导出、历史回溯、只读分享链接 |

### 👤 账户
登录注册 · 账户设置（**模型与数据源配置入口**）· 用户管理（多用户模式）

---

## 快速开始

### 方式一：Docker（推荐，一行命令）

```bash
git clone https://github.com/EEE77773333/FUNDANALYSIS.git && cd FUNDANALYSIS
docker compose up -d
```

打开 <http://localhost:8501> 即可。首次启动会自动建库。

> 不需要预先准备 `.env`。想自定义端口/密码，用 `./quickstart.sh` 生成配置。

### 方式二：本地 Python（最轻量，零配置）

```bash
git clone https://github.com/EEE77773333/FUNDANALYSIS.git && cd FUNDANALYSIS
pip install -r requirements.txt
streamlit run app.py
```

这个模式用 SQLite 单机运行，**免登录**，打开就能用。

### 方式三：群晖 / NAS

1. 在 NAS 上装好 **Container Manager**（原 Docker 套件）
2. 把项目文件放到共享文件夹，例如 `/volume1/docker/fund-analysis`
3. SSH 进入该目录执行 `docker compose up -d`
4. 或在 Container Manager 里「新增项目 → 选择 docker-compose.yml」

数据持久化在项目目录下的 `data/`，迁移或备份直接复制这个文件夹即可。

### 首次登录说明

| 模式 | 账号 |
|---|---|
| 单机版（SQLite） | 自动使用 `local@fund.local`，**免登录** |
| 多用户版（PostgreSQL） | 设置了 `ADMIN_DEFAULT_PASSWORD` 才创建管理员 `admin@fund.local`；否则请在登录页自行注册 |

---


## 配置你自己的 AI 模型

登录后进入 **账户设置 → 🔌 AI 与数据源**，选服务商、填 Key、点「测试连通性」，保存即生效（无需重启）。

| 类型 | 支持的服务 |
|---|---|
| 云端 API | DeepSeek、通义千问、智谱 GLM、Kimi、OpenAI、硅基流动、OpenRouter |
| 原生协议 | Anthropic Claude |
| **本地推理（零成本）** | **Ollama**、vLLM、LM Studio |

**没配 AI 也能用。** 筛选、回测、费率计算、蒙特卡洛等纯本地计算功能完全不受影响，只有需要调用大模型的分析功能会给出配置引导。

### 用本地 Ollama 跑，完全零 API 成本

```bash
ollama pull qwen2.5:7b
ollama serve
```

界面里选「Ollama（本地）」→ 接口地址填 `http://localhost:11434/v1` → 模型填 `qwen2.5:7b`。

> Docker 部署时，容器内访问宿主机要写 `http://host.docker.internal:11434/v1`。

### 想在服务端一次性配好（`.env`）

```bash
LLM_PRESET=deepseek
LLM_API_KEY=sk-xxxxxxxxxxxx
LLM_MODEL=deepseek-chat
```

旧版 `DEEPSEEK_API_KEY` / `ANTHROPIC_API_KEY` 写法**继续兼容**，无需迁移。

---

## 配置行情数据源

在 **账户设置 → 🔌 AI 与数据源** 里切换，或在 `.env` 设置 `DATA_PROVIDER`。

| 数据源 | 需要 token | 说明 |
|---|---|---|
| `eastmoney` | 否 | 东财/天天基金直连，零依赖，默认主力通道 |
| `akshare` | 否 | 覆盖面最广，已含在依赖中 |
| `tushare` | **是** | 持仓与宏观数据更规整，[免费注册](https://tushare.pro) |
| `baostock` | 否 | 日线为主，长周期回测稳定，已含在依赖中 |
| `yfinance` | 否 | **可选**：海外行情，需能访问 Yahoo。国内服务器通常不可用，`pip install yfinance` 后可启用 |

系统按 **东财 → AKShare → Tushare → Baostock** 顺序自动降级，主源失败自动切备用源，并在界面上标注当前数据来源。

> **关于盘中估值**：天天基金的估值接口已于 2024 年前后下线，系统改用 AKShare 全市场估值表兜底。
> 该表覆盖指数型 / ETF 联接等约 700 只基金；**主动管理型基金上游已不再提供盘中估值**，
> 这类基金在「盘中估值中心」会回退展示最新公布净值，属正常现象而非故障。

### 本地缓存（重要）

行情结果会落库缓存，默认 300 秒。这不只是提速 —— 公共数据源有频控，用户一多、请求一密很容易被限流甚至封 IP。缓存把重复请求挡在本地，是自部署长期稳定运行的关键。

可在界面上调整缓存时长，或设 `DISABLE_QUOTE_CACHE=1` 完全关闭。

---

## 常见问题

<details>
<summary><b>没有大模型 API Key 能用吗？</b></summary>

能。筛选、回测、费率计算、蒙特卡洛、导出等纯本地功能全部可用。只有 AI 分析类功能会提示你去配置。想零成本用 AI，可以本地跑 Ollama。
</details>

<details>
<summary><b>AKShare 抓取失败 / 报错怎么办？</b></summary>

AKShare 是公开接口，源站改版时会短期失效，属于正常现象。三个应对办法：
1. 系统已内置多源降级，东财直连通常不受 AKShare 影响，会自动接管
2. 开启本地缓存（默认已开），减少重复请求
3. 在数据源设置里切到 Tushare 或 Baostock
</details>

<details>
<summary><b>数据会传到你的服务器吗？</b></summary>

不会。自部署模式下所有数据都存在你自己的 `data/` 目录里。你的 AI Key 也只保存在本地数据库，界面只回显掩码。
</details>

<details>
<summary><b>怎么升级 / 数据会不会丢？</b></summary>

数据都在 `data/` 目录，升级前复制这个目录即可完整备份。`docker compose up -d --build` 重新构建后会沿用原有数据。
</details>

<details>
<summary><b>支持哪些 Python 版本？</b></summary>

Python 3.10 及以上，推荐 3.12。
</details>

<details>
<summary><b>能在 Windows 上跑吗？</b></summary>

可以。装好 Python 后执行 `pip install -r requirements.txt` 和 `streamlit run app.py` 即可；有 Docker Desktop 的话用方式一更省事。
</details>

---

## 技术栈

| 层 | 选型 |
|---|---|
| 前端 | Streamlit（多页应用 + 自定义主题） |
| AI | OpenAI 兼容协议统一接入（`core/llm_presets.py`） |
| 数据 | 东财直连 / AKShare / Tushare / Baostock / yfinance 多源降级（`core/fetchers/`） |
| 缓存 | 本地 SQLite / PostgreSQL + TTL（`core/data_sources.py`） |
| 存储 | SQLite（单机）/ PostgreSQL（多用户），自动切换 |
| 认证 | bcrypt + 自签 JWT |
| 量化 | pandas / numpy / scipy，Sharpe / Sortino / Calmar / Brinson / 蒙特卡洛 |
| API | FastAPI（可选，`server.py`） |

### 代码结构

```
app.py                    # 入口 + 首页
pages/                    # 34 个功能页面
core/
  ├── llm_presets.py      # LLM 服务商预设注册表
  ├── ai_analyzer.py      # AI 调用引擎（OpenAI 兼容 + Anthropic）
  ├── model_router.py     # 同端点多模型路由与降级
  ├── metering.py         # AI 用量计量（配额基础）
  ├── user_integrations.py# 用户自带密钥 / 数据源配置
  ├── integration_ui.py   # 「AI 与数据源」配置界面
  ├── data_sources.py     # 数据源注册表 + TTL 缓存
  ├── fetchers/           # 各数据源适配器
  ├── data_fetcher.py     # 基金数据获取（主通道）
  ├── middleware.py       # 认证守卫 + 套餐配额
  └── ...
docker-compose.yml        # 一键部署
quickstart.sh             # 一键启动脚本
```

---

## 开源版 vs 云托管版

本项目的定位是 **数据工具 + 量化分析**。

| | 开源自部署（本仓库） | 云托管版 |
|---|---|---|
| 功能 | 全部功能 | 全部功能 |
| 使用次数 | **不限** | 按套餐配额 |
| AI 费用 | 你自己的 Key | 由服务方承担 |
| 行情数据 | 你自己配置 | 稳定中转源 |
| 数据存储 | 本地 | 云端 |
| 监控推送 | 自行配置 | 开箱即用 |
| 适合 | 愿意自己动手、在意数据隐私 | 怕麻烦、想开箱即用 |

写在这里是为了透明：开源版不会被人为阉割功能，需要的只是你愿意自己配一下密钥。

---

## ⚠️ 免责声明

- 本系统是**数据分析工具**，所有输出**不构成任何投资建议**。
- AI 生成内容基于历史数据与公开信息，可能出现错误或幻觉，请独立判断。
- 基金投资有风险，过往业绩不代表未来收益。
- 行情数据来自第三方公开接口，版权归原数据机构所有；本项目仅做技术聚合与本地缓存，不转售数据。
- 请勿将本系统用于任何需要持牌资质的证券投资咨询业务。

> 📄 若你打算**对外托管运营**本系统，请先阅读并落实 [`docs/用户协议.md`](docs/用户协议.md) 与 [`docs/隐私政策.md`](docs/隐私政策.md)。两者为合规模板稿，**上线前必须替换其中的主体信息占位符并经法律顾问审阅**。注册页已内置"必须勾选同意"闸门。

---

## 参与贡献

欢迎提 Issue 和 PR。特别欢迎这几类：

- 新增数据源适配器（在 `core/fetchers/` 下实现 `fetch(method, **kwargs)` 即可）
- 新增 LLM 服务商预设（在 `core/llm_presets.py` 里加一条记录）
- 修复数据源接口失效问题
- 文档改进与部署踩坑经验

---

## License

[AGPL-3.0](LICENSE)

你可以自由使用、修改、自部署；但如果你把修改版作为网络服务提供给他人使用，你也必须公开你的修改源码。

<div align="center">

**如果这个项目对你有帮助，点个 ⭐ Star 是最大的支持**

</div>
