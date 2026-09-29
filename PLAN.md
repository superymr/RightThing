# RightThing 正事 — 项目规划书

> 一句话定位：**输入你会什么，反向推导出「这个方向的市场真正要求什么」，并把你和市场的差距画出来。**
>
> 版本：v1.0 规划稿　|　状态：M1 / M2 / M3 已完成，M5 第一阶段已完成　|　技术栈：FastAPI + React + OpenAI 兼容大模型 API

---

## 1. 项目目标与价值

### 1.1 要解决的问题

求职者（尤其是转行、应届、跨领域的人）常见的困境是：

- 不知道自己的技能组合能匹配哪些岗位；
- 知道岗位名字，但看不懂 JD 里哪些是**真正的高频硬要求**，哪些只是 HR 的客套话；
- 学了一堆东西，却不知道哪些是"这个方向 80% 的岗位都要"的高性价比技能。

### 1.2 本项目的输出

用户输入技能列表 → 系统输出三样东西：

1. **适配的岗位方向列表**（由大模型基于技能组合推荐）；
2. **该方向下的真实 JD 样本**（岗位职责 / 岗位要求原文）；
3. **结构化 + 聚合后的技能图谱**：
   - 需要掌握的编程语言排行（按出现次数）
   - 需要的技能/工具/框架排行
   - 招聘方的"优先考虑对象"（学历、专业、经验、证书、加分项）排行
   - **个人技能缺口清单**（市场要求 − 我已会 = 要学的）

### 1.3 非目标（明确不做，避免范围蔓延）

- ❌ 不做简历生成、投递、自动打招呼（合规与复杂度都过高）
- ❌ 不做实时全站爬取（v1 用可插拔采集层 + 样例数据 + 半自动录入）
- ❌ 不做薪资预测 / Offer 概率预测（数据不足，容易误导用户）
- ❌ 不做用户账号体系与社交功能（v1 单机/单用户）

---

## 2. 核心用户流程（端到端）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ① 用户输入技能                                                             │
│    ["数据分析", "Python", "ROS", "Linux", "C++"]                           │
└────────────────────────────┬─────────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ ② 技能归一化 Skill Normalizer                                              │
│    "数据分析" → Data Analysis (canonical)                                  │
│    "ROS"      → Robot Operating System                                     │
│    并推断技能族： { 编程语言, 数据, 机器人, 系统 }                            │
└────────────────────────────┬─────────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ ③ LLM 调用 #1：岗位方向推荐 + 检索词扩展                                     │
│    输入：归一化后的技能 + 技能族                                            │
│    输出：候选岗位方向（带匹配度理由）、每个方向的检索关键词（中文/英文）        │
│    例： [{ "title": "机器人算法工程师", "score": 0.86,                   │
│            "reason": "...", "keywords": ["机器人算法","ROS开发","SLAM"] }] │
└────────────────────────────┬─────────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ ④ 岗位采集层 Job Source Layer（可插拔）                                     │
│    ┌─────────────┬─────────────┬──────────────┬───────────────────┐      │
│    │ SampleSource│ NowcoderSrc │ ManualPaste  │ 未来: BOSS/拉勾/…  │      │
│    │ (内置样例)   │ (适配器)     │ (手动粘贴)    │                   │      │
│    └─────────────┴─────────────┴──────────────┴───────────────────┘      │
│    统一输出：RawJob { source, url, title, company, raw_text, ... }         │
└────────────────────────────┬─────────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ ⑤ JD 结构化抽取（LLM 调用 #2，逐条/批量）                                    │
│    输入：岗位职责 + 岗位要求原文                                             │
│    输出：严格 JSON（Pydantic 校验）                                         │
│    { hard_skills[], programming_languages[], soft_skills[],               │
│      preferred_qualifications[], education, major, experience,            │
│      certificates[], domain_knowledge[], seniority }                      │
│    ★ 带缓存：同一 JD 文本的 hash 命中直接复用，省 token 保证可复现            │
└────────────────────────────┬─────────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ ⑥ 归一化 + 聚合统计 Aggregation                                             │
│    别名合并： "python3"/"Python 编程" → Python                              │
│    统计： 出现次数、覆盖率(=出现岗位数/总岗位数)、                            │
│          必须 vs 加分 加权分、按岗位方向分组                                  │
└────────────────────────────┬─────────────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ ⑦ 可视化 + 缺口分析 Dashboard                                              │
│    排行条形图 / 技能×方向 热力图 / 雷达图 / 我的技能 vs 市场需求              │
└──────────────────────────────────────────────────────────────────────────┘
```

**关键设计思想**：整个系统是 **LLM 负责"理解与抽取"，代码负责"统计与呈现"**。
绝不让 LLM 负责数数和排名——那是幻觉重灾区。所有排行榜必须由确定性代码从结构化结果中算出。

### 2.1 实施后补上的关键环节（原计划遗漏，实测暴露）

真实模型接入后暴露出一个原计划完全没有覆盖的环节：

```
⑤ 抽取 → ⑤.5 自由文本收敛 ★ 新增
   "PID控制算法"       → "PID控制"
   "团队协作意识"       → "团队协作"
   "嵌入式开发与单片机移植" → "嵌入式开发" + "单片机"   （一个拆成两个）
   "硕士及以上学历"     → "硕士及以上"
   "3年以上SLAM相关研发经验" → "3年以上"
```

**为什么必须放在聚合之前**：mock 规则引擎返回的名字来自词表，天生规范，
所以漏掉这一步在 mock 路径下完全看不出问题。真模型返回自由文本时不收敛，
一次分析会抽出 **97 个「不同」技能**（mock 路径只有 36 个），学历被拆成三行 ——
排行榜与缺口清单同时失效。这是「LLM 只做抽取、代码做统计」这条红线上的接缝处理。

---

## 3. 系统架构

```
┌─────────────────────────── Frontend (React + Vite) ───────────────────────┐
│  ① SkillInput 技能录入页  ② DirectionPicker 方向选择页                      │
│  ③ Dashboard 分析看板页   ④ JobList 岗位明细页（可回溯原始 JD）              │
│  图表： ECharts (柱状/热力图/雷达)　状态： TanStack Query + Zustand          │
└───────────────────────────────────┬───────────────────────────────────────┘
                                    │ REST + SSE
┌───────────────────────────────────▼───────────────────────────────────────┐
│                        Backend (FastAPI)                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ api/ 路由层   │  │ services/    │  │ sources/     │  │ llm/          │  │
│  │ 参数校验      │→ │ 业务编排      │→ │ 采集适配器    │→ │ Provider 抽象 │  │
│  │ 错误映射      │  │ 任务/缓存     │  │ 限流/重试     │  │ Prompt/解析   │  │
│  └──────────────┘  └──────┬───────┘  └──────────────┘  └───────┬───────┘  │
│                           │                                    │          │
│                    ┌──────▼───────┐                    ┌───────▼───────┐  │
│                    │ analytics/   │                    │ OpenAI 兼容 API│  │
│                    │ 归一化+聚合   │                    │ DeepSeek/Kimi… │  │
│                    └──────┬───────┘                    └───────────────┘  │
│                           │                                               │
│                    ┌──────▼───────────────────────────────────────────┐  │
│                    │ SQLite (sqlite3) + llm_cache 表（结果缓存）        │  │
│                    └──────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

### 分层职责

| 层 | 职责 | 不允许做的事 |
|---|---|---|
| `api/` | HTTP 契约、参数校验、错误映射 | 不写业务逻辑、不直接调 LLM |
| `services/` | 编排流程、事务、缓存、任务、看板读回 | 不关心 HTTP，不拼接 SQL |
| `sources/` | 只负责"拿到原始 JD 文本" | 不做结构化抽取、不做统计 |
| `llm/` | Prompt、调用、重试、JSON 校验、成本统计 | 不做业务判断、不写数据库 |
| `analytics/` | 归一化、收敛、聚合、排名、缺口计算 | 不调用外部网络 |
| `models/` | 数据模型、SQLite 访问、轻量迁移 | 无业务逻辑 |

**这个分层是本项目最重要的可维护性保证**：采集站点经常失效，LLM 会被替换，
但中间的分析逻辑应当稳定不变。

---

## 4. 模块详细设计

### 4.1 技能录入与归一化（`analytics/normalizer.py`）

- 用户自由输入 → 先做**规则清洗**（大小写、全半角、去空格、"熟练使用X"剥离）；
- 再查**别名表** `skill_alias.json`（人工维护 + 可增量学习）：
  ```json
  {
    "Python": ["python", "python3", "Python编程", "python语言"],
    "Robot Operating System": ["ROS", "ros1", "ros2"],
    "SQL": ["sql", "sql语言"]
  }
  ```
- 未命中的 → 保留原词作为规范名，并**回写 SQLite `skill_alias` 表**（`source=learned`）；
- 处理真模型自由文本时用**包含匹配**兜底：命中一个就替换，命中多个就拆分。

匹配的两个关键细节（都有对应的回归测试）：

- **边界安全**：`C` 不能匹配到 `C++`，`SQL` 不能匹配到 `MySQL`，`EtherCAT` 不能算成 `CAN总线`；
- **最长优先 + 掩码**：先匹配长别名，命中后把该区段挖空，避免短别名重复命中同一处。

### 4.2 岗位方向推荐（LLM 调用 #1）

**输入**：归一化技能 + 技能族 + （可选）城市/学历/经验年限
**输出**（严格 JSON）：
```json
{
  "directions": [
    {
      "title": "机器人算法工程师",
      "match_score": 0.86,
      "reason": "你的 ROS + C++ + Linux 组合直接命中该岗位核心栈",
      "keywords": ["机器人算法工程师", "ROS开发", "SLAM算法"],
      "related_titles": ["运动控制工程师", "自动驾驶感知工程师"]
    }
  ]
}
```
要点：
- 要求模型给出**同义词与近义岗位名**，这是提升采集召回率的关键；
- `match_score` 仅作排序参考，前端明确标注为"AI 估计值"，避免误导。

### 4.3 采集层（`sources/`）

统一接口——这是"可插拔"的落点：

```python
class JobSource(Protocol):
    name: str
    def search(self, keyword: str, *, city: str | None,
               limit: int = 30) -> list[RawJob]: ...
    def fetch_detail(self, job: RawJob) -> RawJob: ...   # 补齐 JD 全文
```

内置实现（按优先级）：

| 实现 | 用途 | 状态 |
|---|---|---|
| `SampleSource` | 从 `data/samples/*.json` 读预置 JD | ✅ M1 完成 |
| `ManualPasteSource` | 前端/CLI 粘贴 JD 文本 → 入库 | ✅ M1 完成 |
| `NowcoderSource` | 牛客公开 sitemap + `/jobs/detail/*` 适配器 | ✅ M4 第一阶段完成 |
| `NcssSource` | 国家大学生就业服务平台公开列表接口 + 详情页 | ✅ M4 完成 |
| `ShixisengSource` | 实习僧公开搜索页 + 详情页 | ✅ M4 完成 |
| `JobicySource` | 无密钥公共远程岗位 API + 一小时查询缓存 | ✅ M4 完成 |
| `ArbeitnowSource` | 欧洲公开招聘 API + 三页目录缓存 | ✅ M4 完成 |
| `GreenhouseJobSource` | 企业官方公开招聘板 API | ✅ M4 完成 |
| `BraveJobSearchSource` | 联网搜索招聘站与企业官网 | ✅ M4 完成（需 API Key） |
| `PublicJobPageSource` | 任意公开岗位 URL 安全导入 | ✅ M4 完成 |

采集层公共能力：**请求间隔限制**、**单次扫描上限**、**详情与 sitemap 磁盘缓存**、
**故障隔离**（在线源失败不带垮分析）、**规范化**（统一成 `RawJob`，保留
`content_hash` 以便去重）。牛客 `robots.txt` 禁止 `/search`，因此实现只使用公开
sitemap 做发现并读取其中列出的岗位详情；召回率受 sitemap 覆盖范围约束。

### 4.4 JD 结构化抽取（LLM 调用 #2）

这是全项目**质量最敏感的环节**。设计要点：

1. **一次只处理一条 JD**（长文本批量会互相污染），线程池并发，上限 `LLM_MAX_CONCURRENCY`；
2. 使用 **JSON Schema 约束输出**（不支持的端点自动降级为"强提示 + Pydantic 校验"）；
3. 提示词强制规则：
   - 只能从原文中抽取，**禁止推测**；找不到就返回空数组；
   - 每个技能项必须给出 `evidence`（原文片段），便于人工审计与前端高亮；
   - 区分 `required`（任职要求）与 `preferred`（优先/加分）。
4. **缓存**：`sha256(kind | prompt版本 | 词表指纹 | 模型 | JD文本)` → 结果落库。

抽取 Schema（dataclass，等价于 Pydantic）：

```python
class JDProfile:
    job_title: str
    seniority: str
    education: str
    major: list[str]
    experience_years: str
    programming_languages: list[SkillItem]
    hard_skills: list[SkillItem]
    domain_knowledge: list[SkillItem]
    soft_skills: list[SkillItem]
    certificates: list[str]
    preferred_qualifications: list[str]   # ★"优先考虑对象"原文摘录
    responsibilities: list[str]
    summary: str

class SkillItem:
    name: str
    category: str
    required: bool          # True=硬性要求, False=加分项
    evidence: str           # 原文依据（必须是原文子串）
    confidence: float       # 0-1
```

### 4.5 聚合与排名（`analytics/aggregator.py`）

对某个岗位方向下的 N 条 JD：

| 指标 | 定义 | 为什么需要 |
|---|---|---|
| `count` | 提及该技能的 JD 条数 | 用户要的"出现次数排行" |
| `coverage` | `count / N` | 比绝对次数更公平，避免样本量误导 |
| `required_ratio` | 标为必须的占比 | 区分"必须会"和"会更好" |
| `weighted_score` | `Σ(必须=1.0, 加分=0.4)` | 主排序依据 |

排序默认 `weighted_score`，同时把 `coverage` 与 `required_ratio` 一并展示。

### 4.6 技能缺口分析（核心卖点）

```
市场要求集合 R（按 weighted_score 排序）
我的技能集合 M（用户输入，已归一化）
───────────┬──────────────────────────────
已具备      │ R ∩ M        → "你的优势项"
需要补齐    │ R − M        → "学习清单"（按优先级排序）
边缘技能    │ M − R        → "该方向用不上，可暂缓"
```

分档规则：

- **必学**：`coverage ≥ 40%` 且 `required_ratio ≥ 60%`
- **建议学**：`coverage ≥ 20%` 或 `required_ratio ≥ 40%`
- **加分项**：其余

外加一道**噪音闸门**（实测后补充）：只被 1 个岗位提到的技能一律落到加分项。
真实模型的抽取粒度远细于规则引擎，没有这道闸门，「建议学」会从 31 项膨胀到 97 项。

### 4.7 可视化设计（前端，M3）

| 图表 | 内容 | 库 |
|---|---|---|
| 横向条形排行图 | 技能 Top20，按 weighted_score，色分必须/加分 | ECharts Bar |
| 热力图 | 技能 × 岗位方向，颜色=覆盖率 | ECharts Heatmap |
| 雷达图 | 我的技能 vs 市场要求（按技能族聚合） | ECharts Radar |
| 缺口泳道图 | 已具备 / 需补齐 / 边缘技能 三列卡片 | 自研组件 |
| 原文回溯 | 点击任意技能 → 侧栏列出所有含它的 JD 及高亮证据句 | 自研 + 高亮 |

**交互闭环**：任何一个统计数字都要能点回原始 JD 原文 —— 这是建立用户信任的关键，
也是防止 LLM 幻觉影响的防线。

---

## 5. 数据模型

```sql
-- 分析任务（一次用户请求）
analysis_session(id, created_at, input_skills_json, city, llm_provider, llm_model, status)
  -- input_skills_json 存 {"raw": [...], "canonical": [...]}
  -- 存规范名是必需的：读回看板要算缺口，必须用规范名做集合运算

-- 岗位方向
job_direction(id, session_id, title, match_score, reason, keywords_json, selected)

-- 原始岗位（跨会话按 JD 内容去重）
raw_job(id, session_id, direction_id, source, source_job_id, url, title,
        company, city, raw_text, raw_html_path, fetched_at, content_hash)
  UNIQUE(source, source_job_id)

-- 结构化抽取结果（一次抽取 = 会话×方向×岗位 的一份快照）
jd_profile(id, raw_job_id, session_id, direction_id, prompt_version, model,
           profile_json, extraction_status, token_in, token_out, cache_hit, created_at)
  -- ★ 归属关系必须挂在这里而不是 raw_job：
  --   raw_job 跨会话共用，记在它上面会导致同一条 JD 在第二次分析里「找不到」

-- 归一化后的技能（宽表，便于聚合查询）
jd_skill(id, jd_profile_id, raw_job_id, skill_canonical, skill_raw,
         category, required, evidence, confidence)

-- 技能别名表（可增量学习）
skill_alias(id, canonical, alias, source, created_at)
  -- source: manual | llm | learned

-- 缓存
llm_cache(cache_key, kind, model, prompt_version, response_json, created_at, hit_count)
```

> v1 用 SQLite（零部署成本）。所有 SQL 只出现在 `models/` 与 `services/`，
> 上层不拼 SQL —— v2 换 Postgres 只需替换 `models/db.py`。
>
> `init_schema()` 内含**轻量迁移**：建表 → 补列 → 建索引。
> 顺序不能变，索引引用了后加的列，先建索引会在旧库上炸「no such column」。

---

## 6. API 设计（FastAPI）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 健康检查（`?deep=true` 触发一次真实 LLM 调用） |
| `GET` | `/api/directions` | 数据源配置（保留旧接口名以兼容前端） |
| `POST` | `/api/skills/normalize` | 技能归一化预览（用户确认后再继续） |
| `POST` | `/api/analyze` | LLM#1 + 采集 + LLM#2 + 聚合（默认异步，返回 task_id） |
| `GET` | `/api/tasks` | 任务列表 |
| `GET` | `/api/tasks/{id}` | 任务状态（轮询兜底） |
| `GET` | `/api/tasks/{id}/events` | **SSE 进度流** |
| `GET` | `/api/sessions` | 历史分析列表 |
| `GET` | `/api/sessions/{id}` | 完整看板（一次性聚合，减少前端请求数） |
| `GET` | `/api/jobs/{id}` | 原始 JD 全文 + 结构化结果 + 证据句 |
| `POST` | `/api/jobs/manual` | 手动粘贴 JD 入库并立即抽取 |

**长任务处理**：`POST /api/analyze` 返回 `task_id`，进度经
`GET /api/tasks/{id}/events`（SSE）推送，前端显示「已采集 12/30，已解析 8/30」。

三个实现上的硬要求：

1. **事件留档**：SSE 客户端可能晚连，必须回放历史事件，否则早期进度永久丢失；
2. **心跳**：每 15 秒发一个 SSE 注释行 —— 反向代理在 30~60 秒无数据时会掐断连接；
3. **结果不进任务对象**：任务只返回精简摘要，完整看板按 `session_id` 从数据库读回。
   这样服务重启后历史仍可查，多 worker 部署也不会「请求打到另一个进程就查不到」。

**错误契约**：统一 `{"error": {"code", "message", "detail"}}`。
其中 `llm_not_configured` / `llm_unavailable` 返回 **503 而不是 500** ——
那是配置或上游依赖问题，不是本服务的 bug，混进 500 会误导排查方向。

---

## 7. 技术选型清单

**后端**
```
M1 核心（零依赖）：标准库 urllib / sqlite3 / json / re / dataclasses
M2 HTTP 层：fastapi, uvicorn[standard], pydantic v2
可选：httpx（接入真实 LLM 时）
```
> 有意**不引入** SQLModel / structlog：单进程 + 少量并发下，
> 它们的收益抵不过多一个依赖的成本。汇总 SQL 只在 `models/db.py`，
> 日志用标准库 `logging`。

**前端（M3）**
```
react + vite + typescript
@tanstack/react-query（服务端状态）, zustand（本地状态）
echarts
tailwindcss + shadcn/ui
react-hook-form + zod
```

**LLM 配置**（`.env`）
```
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=deepseek-flash
LLM_MAX_CONCURRENCY=5
LLM_TEMPERATURE=0
```
> **`temperature=0` 是硬性要求**：抽取任务需要可复现、可对比。
>
> **模型名必须与端点 `/models` 返回的一致**。实测踩过的坑：
> 填 `deepseek-chat` 时端点不报错，而是**静默回退到最弱的模型** ——
> 用户以为在用 A，实际跑的是 B。`jobradar doctor` 的模型名检查就是为此而生。

---

## 8. 目录结构

```
job-skill-radar/
├── PLAN.md
├── README.md
├── .env / .env.example
├── .gitignore
└── backend/
    ├── pyproject.toml
    ├── conftest.py
    ├── app/
    │   ├── main 入口：cli.py / server.py / __main__.py
    │   ├── config.py
    │   ├── report.py
    │   ├── doctor.py            # 环境自检
    │   ├── api/                 # app.py / deps.py / errors.py / schemas.py
    │   │                        # static.py（托管前端构建产物）/ routes/
    │   ├── services/            # orchestrator.py / tasks.py / dashboard.py / cache.py
    │   │                        # aliases.py（别名提升闭环）/ export.py（Markdown 导出）
    │   ├── sources/             # base.py / sample.py / manual.py
    │   ├── llm/                 # base.py / openai_provider.py / mock_provider.py
    │   │                        # extractor.py / schemas.py / prompts/
    │   ├── analytics/           # lexicon.py / normalizer.py / canonical.py
    │   │                        # aggregator.py / gap.py
    │   ├── models/              # db.py（含轻量迁移）
    │   └── utils/               # logging.py / timeutil.py / sanitize.py（脱敏）
    ├── data/
    │   ├── samples/             # 内置样例 JD（2 个方向 × 12 条）
    │   └── skill_alias.json
    ├── tests/                   # 287 个测试
    └── tools/                   # check_reproducible.py / smoke_api.py
└── frontend/                    # M3：React + Vite + TS 看板
    ├── src/
    │   ├── api/                 #   types.ts（契约）/ client.ts / hooks.ts
    │   ├── components/          #   charts/ · SkillDrawer · Layout · ui
    │   ├── pages/               #   录入 / 进度 / 看板 / 岗位 / 历史 + 组件回归测试
    │   ├── test/                #   Vitest / Testing Library 测试环境
    │   ├── store/               #   zustand（只放前端本地状态）
    │   └── utils/highlight.ts   #   证据句定位与高亮
    └── dist/                    #   构建产物，后端自动托管
```

---

## 9. 合规与风险（必须重视）

| 风险 | 说明 | 应对 |
|---|---|---|
| **反爬与封禁** | 牛客/BOSS 有登录墙、验证码、频率限制 | 严格限流、遵守 `robots.txt`、默认关闭真实站点采集、优先手动粘贴 |
| **法律合规** | 大规模抓取 JD 可能违反用户协议；JD 文本有著作权属性 | v1 定位**个人学习研究用途**、数据仅本地存储、不对外分发；提供免责声明 |
| **个人信息** | JD 中可能含 HR 姓名/联系方式 | ✅ 已实现：入库与抽取**之前**对手机号/邮箱/身份证/微信/银行卡做幂等脱敏（`utils/sanitize.py`），明文不落库也不发给模型 |
| **LLM 幻觉** | 模型可能"抽"出原文没有的技能 | 强制 `evidence` 字段 + 前端可回溯原文 + `confidence` 阈值过滤 |
| **模型输出不稳定** | JSON 解析失败、字段缺失 | JSON Schema 约束 + 校验 + 自动重试 + 失败入库标记 |
| **模型名静默回退** | 填错模型名时端点不报错，悄悄用别的模型 | `doctor` 拉 `/models` 核对；缓存键含模型名 |
| **成本失控** | 每条 JD 一次调用，规模化后费用上升 | 结果缓存 + `content_hash` 去重 + 并发上限 + token 计量 |
| **样本偏差** | 30 条 JD 的统计不代表全市场 | 前端显著标注样本量 N，并提供 `coverage` 而非仅 `count` |
| **规则引擎精度** | 别名过宽会产生静默误报 | `doctor` 做 mock vs 真模型的逐项对比；词表边界有回归测试 |

---

## 10. 里程碑规划

### M1 — 地基与可跑通的最小闭环（约 1 周）✅ 已完成
- [x] 项目骨架、`.env` 配置、LLM Provider 抽象层（可切换 base_url/model）
- [x] 数据模型 + SQLite 建表
- [x] `SampleSource` + 24 条真实感 JD 样例数据（覆盖 2 个岗位方向）
- [x] LLM#2 结构化抽取跑通，校验 + 缓存生效
- [x] 命令行脚本 `python -m app.cli analyze --skills "Python,ROS,数据分析"` → 打印排行

**交付标准**：命令行能输出一份技能排行，且重跑命中缓存、结果完全一致。✅

### M2 — 后端 API 完整化（约 1 周）✅ 已完成
- [x] 全部 REST 路由 + SSE 进度推送
- [x] `ManualPasteSource` + 手动录入接口
- [x] 聚合统计与缺口分析模块 + 单元测试
- [x] 错误处理、日志、token 计量

**M2 实施说明（与原计划的差异）：**

| 计划 | 实际 | 原因 |
|---|---|---|
| `structlog` | 标准库 `logging` | 单进程 + 少量并发，结构化日志的收益抵不过多一个依赖 |
| 响应也用 Pydantic 建模 | 请求严格建模，分析结果返回 dict | 结果的形状已由 `report.to_dict()` / `dashboard.py` 定义，再写一套模型等于把同一契约写两遍，两边一旦不同步就会「文档说 A、实际返回 B」 |
| 结果存在任务对象里 | 任务只返回精简摘要，完整看板按 `session_id` 从数据库读回 | 看板不依赖进程内存：服务重启后历史仍可查，多 worker 部署不会「查不到」 |

**新增的验收项（原计划未提但必须做）：**
- 长任务的**事件留档**：SSE 客户端可能晚连，必须回放历史事件
- SSE **心跳**：反向代理在 30~60 秒无数据时会掐断连接
- 轻量 **schema 迁移**：`CREATE TABLE IF NOT EXISTS` 不给旧表加列，
  升级过代码的人会撞上启动即崩的「no such column」

### M3 — 前端可视化看板（约 1.5 周）✅ 已完成
- [x] 技能录入页（带归一化预览与用户确认）
- [x] 方向选择页（展示 match_score 与理由）
- [x] Dashboard：条形排行 / 热力图 / 雷达图 / 缺口泳道
- [x] 原文回溯：点技能看 JD 与高亮证据

**交付标准**：用户从输入技能到看到完整看板，全程无需接触命令行。✅
**接口已就绪**：`GET /api/sessions/{id}` 的返回结构与 `report.to_dict()` 对齐，前端可直接消费。

**M3 实施说明（与原计划的差异）：**

| 计划 | 实际 | 原因 |
|---|---|---|
| `tailwindcss + shadcn/ui` | 只用 Tailwind，UI 原语手写在 `components/ui.tsx` | 看板只需要卡片/按钮/徽章/进度条几种组件，引入整套设计系统 + CLI 生成器的收益抵不过依赖成本（与后端不引入 SQLModel / structlog 是同一个判断） |
| 前端独立部署 | 后端在 `frontend/dist` 存在时托管它（`api/static.py`） | M3 的交付标准是「全程无需接触命令行」。若看板只能靠 `npm run dev` 起第二个服务，用户仍要记两个端口，标准就没达到 |
| —— | 前端 `src/api/types.ts` 显式复写后端契约 | 后端刻意不给分析结果建 Pydantic 模型（见 §6），前端于是成了唯一持有这份类型的地方。字段名写错只会静默变成 `undefined`、图表画成空白 —— 必须有一处显式声明并靠类型检查兜住 |

**新增的验收项（原计划未提但必须做）：**
- **SPA fallback 必须排除 `/api/*`**：否则拼错的接口路径会返回 200 + HTML，
  前端把它当成「接口返回了奇怪的东西」，排查方向被彻底带偏（有回归测试）。
- **SSE + 轮询双通道**：反向代理会掐断 SSE。轮询不只是兜底，它还负责判定任务真的结束了，
  避免前端靠超时去猜。
- **看板数据不进 zustand**：服务端数据一旦拷进本地 store 就有两份真相，
  等于放弃了「服务重启后历史仍可查」这条后端保证。


### M4 — 真实站点采集（约 1 周，视合规情况决定是否启动）
- [x] `NowcoderSource` 实现（公开 sitemap + 详情页、限频 + 缓存 + 故障隔离）
- [x] 采集健康度监控（`GET /api/sources/health`：成功/失败/缓存量/最近错误）
- [x] 前后端采集源开关；产品路径只保留真实在线源，样例仅作测试夹具
- [x] 可选 Brave Search API 适配器（需要用户自己的合法 API Key）
- [x] Jobicy 公共招聘 API 与企业官方 Greenhouse Job Board API
- [x] 国家大学生就业服务平台、实习僧两个中国大陆公开岗位源
- [x] 中英文岗位检索词、多来源配额、按真实 URL 跨源去重
- [x] 中国大陆市场硬过滤（排除港澳台、Worldwide 与海外 Remote）
- [x] 在线采集全任务时间预算、可见扫描进度、用户取消任务
- [x] 牛客岗位详情 URL 直接导入（绕过 sitemap，适合小众岗位）
- [x] 通用公开招聘页导入（JobPosting JSON-LD + 正文降级 + SSRF/重定向防护）
- [ ] 浏览器 E2E：在线源失败提示、长时间索引进度与手动粘贴降级路径

### M5 — 打磨与增强（持续）
- [x] **JD 文本脱敏** —— `utils/sanitize.py`，入库与抽取之前完成（原为第 9 节待办）
- [x] **技能别名表自学习闭环** —— `alias list / promote / merge`，写回 `skill_alias.json`
- [x] **报告导出（Markdown）** —— `report` 命令 + `GET /api/sessions/{id}/report.md`
- [ ] 历史快照对比 → 技能趋势曲线（升温/降温）
- [ ] 学习路径生成（把"必学清单"再交给 LLM 排学习顺序 + 推荐资源）
- [ ] 报告导出 PDF（Markdown 已可用，PDF 需要额外依赖，收益待评估）
- [ ] 多城市、多学历条件的对比分析
- [ ] 按 JD 难度动态选择模型（简单 JD 用快模型，疑难的升级到强模型）

**M5 第一阶段实施说明：**

| 计划 | 实际 | 原因 |
|---|---|---|
| 「抽取后对手机号/邮箱做正则脱敏」 | 扩展为手机/座机/邮箱/身份证/微信/银行卡，且放在**入库与抽取之前** | 放在展示层打码只是「看起来合规」：明文照样落库、照样发给模型。更重要的是抽取用的文本必须与存库文本是同一份，否则 `evidence` 不再是原文子串，前端高亮与幻觉度量一起失效 |
| —— | 脱敏**幂等** + 样例 JD **一字不改**两道约束 | 非幂等会让同一条 JD 两次分析得到不同 `content_hash`，去重直接废掉；正则写宽一点就能「多抓」，但会把「3年以上经验」「微信小程序」改坏 |
| 别名表「LLM 判定结果回写」 | 先做**人工闭环**（list/promote/merge 写回 json） | LLM 自动判定合并需要额外一次调用且会引入新的误判面；人工闭环先解决「学到了但用不上」这个更基础的断层 |
| 报告导出 Markdown / PDF | 只做 Markdown | PDF 要引入渲染依赖（本项目核心链路至今零第三方依赖）；Markdown 可 diff、可 Git 管理、可贴进笔记 |
| —— | 导出复用 `dashboard.load_session()` 的 payload | 导出若自己重新聚合，会出现「网页写 83%、导出写 92%」这种最伤信任的不一致，且往往几个月后才被发现 |


---

## 11. 关键设计决策记录（ADR）

| # | 决策 | 理由 | 备选方案与为何不选 |
|---|---|---|---|
| 1 | **LLM 只做抽取，代码做统计** | 数数和排名是 LLM 幻觉重灾区 | 让 LLM 直接输出排行榜 → 不可复现、无法审计 |
| 2 | **采集层做成 Protocol 接口** | 站点易失效、合规风险高，必须能随时替换/降级 | 直接写死牛客爬虫 → 站点一改全盘皆输 |
| 3 | **样例数据 + 手动粘贴作为 v1 主路径** | 保证 demo 稳定可复现，零合规风险 | 一上来就爬真实站点 → 开发被反爬拖死 |
| 4 | **每次抽取强制带 `evidence`** | 可审计、可回溯，是对抗幻觉最有效的手段 | 只存技能名 → 用户无法验证，信任度低；幻觉也无法量化 |
| 5 | **`temperature=0` + 结果缓存** | 分析类产品必须可复现 | 随机采样 → 同一输入两次结果不同，用户困惑 |
| 6 | **SQLite 起步** | 零部署成本，个人工具足够 | 直接上 Postgres → 增加上手门槛，收益不明显 |
| 7 | **SSE 而非 WebSocket** | 进度推送是单向的，SSE 更简单、更易调试 | WebSocket → 过度设计 |
| 8 | **前端所有数字可点回原文** | 把"信任"设计进交互里，而不是靠文案声明 | 只展示聚合结果 → 用户无法判断真假 |
| 9 | **自由文本在聚合前收敛**（实测补充） | 真模型输出粒度不一，不收敛会让 40 项技能炸成 97 项 | 在聚合层做归一化 → 会把纯函数层变成有状态层，且历史报表随词表漂移 |
| 10 | **持久化归一化后的 profile** | 读回的历史分析必须与当时一致 | 存原始输出、读回时再归一化 → 词表一改，历史报表悄悄变了 |
| 11 | **看板从数据库读回，不从任务对象取** | 不依赖进程内存；重启可查、多 worker 不会查不到 | 结果留在内存 → 「历史分析」只是摆设 |
| 12 | **模型名用 `/models` 核对** | 端点会静默回退到别的模型，不报错 | 相信配置文件 → 用户以为在用 A，实际跑 B |
| 13 | **单次出现的技能不进建议清单** | 那是噪音不是市场信号 | 只按 required_ratio 分档 → 「建议学」膨胀到 97 项，失去指导意义 |
| 14 | **前端构建产物由 FastAPI 托管** | 「全程无需接触命令行」是 M3 的交付标准；起两个服务就不算达标 | 前端独立部署 → 用户要记 5173/8000 两个端口，还要自己配跨域 |
| 15 | **SPA fallback 显式排除 `/api/*`** | 否则拼错的接口路径返回 200 + HTML，前端会当成「接口返回了奇怪的东西」，排查方向被带偏 | 无差别 fallback → 一个笔误换来半小时的无效排查 |
| 16 | **前端显式复写后端返回契约（`api/types.ts`）** | 后端刻意不为分析结果建模型，前端是唯一持有这份类型的地方；写错字段名只会静默变 `undefined` | 用 `any` 接 → 图表画成空白且不报错，属于最难查的 bug |
| 17 | **脱敏放在入库与抽取之前，且必须幂等** | 展示层打码只是「看起来合规」，明文照样落库、照样发给模型；放在最前面还能保证抽取文本与存库文本是同一份，`evidence` 是原文子串这条不变量自动成立 | 展示时脱敏 → 明文泄留；非幂等 → 同一条 JD 两次分析 `content_hash` 不同，去重失效 |
| 18 | **别名提升写回 `skill_alias.json`，不是数据库** | json 是 `SkillLexicon` 唯一读取的词表；只写数据库等于改影子副本，重启即丢 | 只写 DB → 「学到了」永远不生效，长尾越积越多 |
| 19 | **报告导出复用看板 payload** | 同源才能保证「网页上写 83%、导出写 92%」这类不一致不可能发生 | 导出自己重新聚合 → 两套渲染必然漂移，且往往几个月后才被发现 |

---

## 12. 成功评估指标

| 维度 | 指标 | 目标 | 实测 |
|---|---|---|---|
| 抽取质量 | 技能抽取的 evidence 合法率（原文子串比例） | ≥ 95% | 100%（mock 与 flash 实测） |
| 抽取质量 | 结构化输出一次解析成功率 | ≥ 98% | 100%（24 条样例） |
| 性能 | 24 条 JD 端到端耗时（mock / flash） | 越短越好 | 0.4 秒 / 26 秒 |
| 成本 | 单次完整分析 LLM 费用 | < 1 元 | 24 条 × ~3000 token，远低于 1 元 |
| 可用性 | 缓存命中后重跑耗时 | < 10 秒 | 0.15 秒 |
| 可复现 | 同一输入两次运行结果是否逐字节一致 | 必须一致 | ✅ 冷启动与热缓存均通过 |
| 价值验证 | 用户能从"必学清单"中挑出 ≥ 3 项开始学习 | 定性验证 | 待 M3 后验证 |

---

## 13. 已识别的遗留问题

1. **在线岗位召回仍受 sitemap 覆盖限制** —— ✅ M4 第一阶段已在样例未覆盖时查询
   牛客公开 sitemap，但站点禁止抓取 `/search`，所以 sitemap 没列出的历史/长尾岗位
   仍可能返回 0 条。后续应接入有明确授权与 API Key 的搜索服务；0 条只能解释为
   “当前数据源未召回”，不能解释为市场上没有岗位。
2. **技能长尾** —— 真模型抽取粒度细，仍有约 15~48 项只在单个岗位出现。
   已通过报告折叠处理；**工具侧的收敛闭环已完成**（`alias list/promote/merge`
   写回 `skill_alias.json`），但词表本身仍需要人工判断哪些自由文本该归并。
3. **别名表仍以人工判断为主** —— 已实现 learned 回写与提升工具，但「LLM 判定
   某两条是不是同一个技能」还没做（会多一次调用，也引入新的误判面）。
4. ~~JD 文本脱敏未实现~~ —— ✅ M5 已完成，且扩展到身份证/微信/银行卡。
5. **多 worker 部署未验证** —— 看板读回已不依赖内存，但 `TaskManager` 是进程内的，
   多 worker 下任务状态不共享（需要 Redis 或粘性会话）。
6. **前端端到端测试仍不足** —— ✅ 已建立 Vitest + Testing Library 组件测试基线，
   首批 3 条用例覆盖「URL 直达无样本方向」「会话完全无方向」「图表渲染异常被局部隔离」。
   后端 287 个测试继续覆盖统计口径；尚未补齐的是浏览器级（Playwright）测试，
   所以 canvas 图表是否真正绘制、SSE 与轮询在真实浏览器中的协同仍需人工或 E2E 验证。

   > 这条不是假想的风险，已经真实发生过一次：真模型推荐出样例数据没覆盖的方向时，
   > 该方向的技能数组全为空，ECharts 的 radar 拿到空 `indicator` 直接抛异常。
   > 异常发生在 `useEffect` 里，而当时没有错误边界 —— React 卸载了整棵组件树，
   > 用户看到的是一个**全白页面**，既不知道哪里错了，也不知道是不是自己点错了。
   >
   > 修复分三层：`SkillRadar` 显式守卫空数据（治根因）、`useChart` 把 `setOption`
   > 包进 try/catch（图表失败不再外溢）、`ErrorBoundary` 兜住渲染期意外（任何面板
   > 失败都不再带走整页）。现在组件回归测试已经把这条路径锁住；下一步是补浏览器级
   > E2E，验证真实 ECharts canvas 与接口联调，而不只验证 React 输出。
7. **echarts 全量引入** —— `echarts` 打包后约 1.05 MB（gzip 350 KB），
   已经通过 `manualChunks` 单独分包，但尚未按需（`echarts/core` + 按图注册）裁剪。
