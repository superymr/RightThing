# RightThing 正事

[![CI](https://github.com/superymr/RightThing/actions/workflows/ci.yml/badge.svg)](https://github.com/superymr/RightThing/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-indigo.svg)](LICENSE)

> **输入你会什么，反向推导出这个方向的市场真正要求什么，并画出你与市场之间的技能缺口。**

比如你输入 `数据分析、Python、ROS、Linux、C++`，得到的不只是一句「你可以做机器人算法工程师」，而是：

- 机器人算法工程师岗位里，**C++ 出现率 83%、ROS 75%、Linux 75%**；
- 想要拿到这方向的面试，你还缺 **Git（50% 岗位要求）和 Docker（42%）**；
- 招聘方最常写的加分项是「有机器人相关竞赛或开源项目经历」（42% 的岗位提到）；
- 学历要求 **本科 50% / 硕士 50%**，专业偏好 **自动化 75%、计算机 50%**；
- 而你的「数据分析」技能在这个方向上**用不上**，可以暂缓投入。

---

## 30 秒上手

无需安装任何依赖，只要 **Python 3.10+**：

```bash
cd backend
python -m app.cli analyze --skills "数据分析,Python,ROS,Linux,C++"
```

仓库仍保留 **mock 规则引擎**与 24 条合成 JD 作为自动化测试夹具，但产品运行路径
默认不再使用样例岗位。实际分析来自在线岗位源、搜索 API 或你直接导入的职位 URL。

其他常用命令：

```bash
# 启动 HTTP 服务（M2）：交互式文档在 http://127.0.0.1:8000/docs
python -m app.cli serve --port 8000

# 对运行中的服务做冒烟测试（走真实网络栈与 SSE 流）
python tools/smoke_api.py http://127.0.0.1:8000

# 环境自检：配置 / 连通性 / 模型名 / 抽取质量对比（配完 Key 第一件事就做这个）
python -m app.cli doctor

# 只分析某一个方向
python -m app.cli analyze --skills "ROS,C++,Linux" --direction 机器人

# 分析你自己粘贴的 JD（最强合规方案：没有任何爬取行为）
python -m app.cli analyze --jd-file my_jd.txt

# 导出完整结构化结果（给前端或二次分析用）
python -m app.cli analyze --skills "SQL,Python,Excel" --json out/result.json

# 把某次历史分析导出成 Markdown（与看板同源，可直接贴进笔记）
python -m app.cli report 3 --out out/report.md

# 看看系统学到了哪些词表里还没有的技能（真模型路径下这一步很关键）
python -m app.cli alias list
python -m app.cli alias promote "回环检测" --to SLAM --dry-run   # 先预览
python -m app.cli alias promote "回环检测" --to SLAM             # 确认后写回词表

# 校验结果可复现性（同一输入两次运行必须完全一致）
python tools/check_reproducible.py "数据分析,Python,SQL"
```

---

## 可视化看板（M3）

不想碰命令行？构建一次前端，之后一个端口就够了：

```bash
cd frontend && npm install && npm run build
cd ../backend && python -m app.cli serve --port 8000
# 打开 http://127.0.0.1:8000/
```

后端在 `frontend/dist/index.html` 存在时会自动托管它（`app/api/static.py`），
所以**生产形态只有一个进程、一个端口**。开发时仍可用 Vite（有 HMR）：
`cd frontend && npm run dev` → http://localhost:5173 ，`/api` 会被代理到 8000。

看板包含五个页面：

| 路由 | 页面 |
|---|---|
| `/` | 技能录入 → **归一化预览确认** → 启动分析 |
| `/analyze?task=<id>` | SSE 进度时间线 + 方向选择（match_score / 理由 / 检索词） |
| `/sessions/:id` | 分析看板：缺口泳道 / 排行 / 雷达 / 热力图 / 招聘方偏好 |
| `/jobs/:jobId` | 岗位详情：JD 原文 + 证据高亮 + **幻觉度量** |
| `/history` | 历史分析（从数据库读回，服务重启后仍在） |
| `/settings` | 自定义模型 API：测试连接、保存并即时切换模型 |

**任何一个技能标签都可以点开**：右侧会列出所有提到它的 JD，并把证据句高亮出来。
这不是装饰 —— 它是「把信任设计进交互里」的落点，也是对抗 LLM 幻觉的防线。
岗位详情页还会顺手算出**证据合法率**（evidence 必须是原文子串的比例），
把「模型有没有编造」变成一个可以被量化的数字。

右上角的**「导出 Markdown」**会把当前这次分析导出成一份报告。它的数据来源与看板
完全相同（同一个 `dashboard.load_session()` 结果），所以不会出现「网页上写 83%、
导出的文件里写 92%」这种最伤信任的不一致。也可以走命令行：
`python -m app.cli report <session_id> --out report.md`。

---

## 让词表越用越准（`alias` 命令）

这是**接上真实大模型之后才会暴露**的一环，值得单独讲。

mock 规则引擎的技能名来自词表，天生规范。真模型抽的却是自由文本：

```
伺服驱动器参数调试 / 位姿图优化 / 回环检测 / 动力学建模 / 非线性优化
```

系统遇到不认识的词，会把它以「自身为规范名」登记进 SQLite（`source=learned`），
但**真正被 `SkillLexicon` 读取的词表是 `data/skill_alias.json`** —— 不写回 json，
「学到了」就只是躺在一张没人看的表里，下次分析照样把它当成一个独立技能，
排行榜被一点点稀释。

`alias` 命令补的就是这个断层：

```bash
python -m app.cli alias list                    # 看看学到了哪些（按被多少条 JD 抽到排序）
python -m app.cli alias promote "回环检测" --to SLAM --dry-run
python -m app.cli alias promote "回环检测" --to SLAM
python -m app.cli alias merge ROS操作系统 --into ROS
```

三个细节值得说明：

- **写回的是 json，不是数据库** —— json 是词表的单一事实来源，只写数据库等于改影子副本；
- **改完缓存自动失效** —— `cache_namespace` 里带词表的 sha256 指纹，所以不会出现
  「我明明改了词表，结果怎么没变」这种几乎无法排查的现象；
- **文件排版不打乱** —— 词表是「一行一个技能、按类别分组」的手工可编辑格式，
  写入时保持这个格式（有逐字节往返测试兜住），否则以后每次真实改动都会淹没在格式 diff 里。

---

## 个人信息脱敏

JD 正文里经常夹着 HR 的手机号、邮箱、微信号 —— 那是招聘方的个人信息。系统在
**入库与抽取之前**就做脱敏（`app/utils/sanitize.py`）：

```
13812345678            → 138****5678
zhang.san@example.com  → z***@example.com
110101199003071234     → ******************   （整串打码，生日与地区都不能留）
微信：hr_recruit2024    → 微信***
```

放在最前面而不是展示时打码，有两个原因：明文根本不该落库、也不该整段发给模型；
更重要的是**抽取用的文本与存库的文本必须是同一份** —— 否则 `evidence` 就不再是
「原文子串」，前端高亮与幻觉度量会一起失效。

脱敏是**幂等**的（打过码的文本再跑一次不变），否则同一条 JD 两次分析会得到
`content_hash` 不同的两条记录，去重就废了。也刻意保守：24 条内置样例 JD 必须
**一字不改**，这条有专门的回归测试。

---

## 接入真实大模型

复制 `.env.example` 为项目根目录的 `.env`，填写任意 **OpenAI 兼容端点**
（DeepSeek / Kimi / 通义 / OpenAI / vLLM / Ollama 均可）：

```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxxxxxxx
LLM_MODEL=deepseek-chat
```

**然后先自检，再分析：**

```bash
python -m app.cli doctor
```

`doctor` 会依次做四件事，把「配好了但跑不通」拆成可定位的故障点：

1. **配置检查** —— 必填项是否齐全（Key 只显示首尾几位，不会回显明文）；
2. **连通性检查** —— 端点能否访问、**模型名是否真在 `/models` 列表里**、
   鉴权与配额是否正常。模型名写错是最常见的坑，而且原始报错往往只是一句含糊的 400；
3. **抽取质量对比** —— 用同一条 JD 分别跑 mock 基线与真实模型，并排比较技能数与耗时；
4. **幻觉检查** —— 统计 `evidence` 不在原文中的比例。

第 4 项是这个项目特有的：因为抽取契约强制要求每条技能给出原文依据，
所以「模型有没有编造」是可以被**量化**的，而不是靠感觉。合法率低于 80% 会告警。

自检通过后再跑完整分析：

```bash
python -m app.cli analyze --skills "数据分析,Python,RL,大模型"
```

换模型只改 `.env`，代码零改动 —— Provider 抽象层把所有差异隔离在 `app/llm/` 内。

---

## HTTP API（M2）

```bash
cd backend
python -m app.cli serve --port 8000
# 交互式文档： http://127.0.0.1:8000/docs
```

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 健康检查（`?deep=true` 会真的调一次大模型） |
| `GET` | `/api/directions` | 当前岗位数据源配置（兼容旧接口名） |
| `GET` | `/api/settings/llm` | 读取模型配置（API Key 只返回是否已配置及脱敏提示） |
| `POST` | `/api/settings/llm/test` | 使用尚未保存的参数测试模型连通性 |
| `PUT` | `/api/settings/llm` | 保存模型配置到 `.env` 并立即应用 |
| `POST` | `/api/skills/normalize` | 技能归一化预览（跑分析前先让用户确认理解是否正确） |
| `POST` | `/api/analyze` | **启动分析**，默认异步返回 `task_id` |
| `GET` | `/api/tasks/{id}` | 任务状态（SSE 被代理掐断时的轮询兜底） |
| `GET` | `/api/tasks/{id}/events` | **SSE 进度流** |
| `GET` | `/api/sessions` | 历史分析列表 |
| `GET` | `/api/sessions/{id}` | 完整看板（排行榜 + 缺口分析 + 岗位明细） |
| `GET` | `/api/sessions/{id}/report.md` | 导出 Markdown 报告（与看板同源） |
| `GET` | `/api/jobs/{id}` | 岗位原文 + 结构化结果 + 证据句 |
| `POST` | `/api/jobs/manual` | 手动粘贴一条 JD 并立即抽取 |

### 长任务：为什么默认异步

一次分析要几十秒到几分钟。同步请求会被浏览器或网关掐断，用户也看不到进展。所以：

```bash
# 1. 启动，立刻拿到 task_id
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"skills": ["数据分析", "Python", "ROS", "C++"]}'

# 2. 订阅进度流
curl -N http://127.0.0.1:8000/api/tasks/<task_id>/events
#   event: normalize
#   data: {"stage":"normalize","message":"正在归一化输入技能",...}
#   event: extract
#   data: {"stage":"extract","message":"「机器人算法工程师」已解析 7/12：...","current":7,"total":12}
#   event: done

# 3. 用 task 结果里的 session_id 取完整看板
curl http://127.0.0.1:8000/api/sessions/1
```

三个刻意的设计选择：

- **事件留档**：SSE 客户端可能在任务开始后才连上，所以新订阅者会先收到历史事件回放，
  否则「正在归一化技能」那一步会永久丢失。
- **心跳**：每 15 秒发一个 SSE 注释行。反向代理通常在 30~60 秒无数据时掐断连接。
- **结果不进任务对象**：任务结果只返回精简摘要，完整看板按 `session_id` 从**数据库**读回。
  因此服务重启后历史分析依然可查，多 worker 部署也不会「请求打到另一个进程就查不到」。

### 错误契约

所有错误统一成 `{"error": {"code", "message", "detail"}}`，前端靠 `code` 决定展示方式：

| code | HTTP | 含义 |
|---|---|---|
| `empty_input` | 422 | 既没给 skills 也没给 jd_texts |
| `validation_error` | 422 | 参数越界等，`detail` 里带字段路径 |
| `not_found` | 404 | 会话 / 岗位 / 任务不存在 |
| `llm_not_configured` | 503 | 没配 Key —— `detail.hint` 直接告诉用户改哪个文件 |
| `llm_unavailable` | 503 | 上游调用失败（Key 失效、余额不足、模型名错） |
| `internal_error` | 500 | 未预期异常，服务端已记录堆栈 |

**503 而不是 500** 是有意的：这是上游依赖不可用，改配置或重试就能解决，不是本服务的 bug。

---

## 它是怎么工作的

```
① 技能输入 → ② 归一化 → ③ LLM#1 推荐岗位方向 + 检索词
                                   ↓
                        ④ 采集层取回 JD 原文
                                   ↓
                        ⑤ LLM#2 把 JD 抽成结构化 JSON
                                   ↓
                        ⑥ 代码统计聚合（排名/覆盖率/加权分）
                                   ↓
                        ⑦ 技能缺口分析 + 可视化看板
```

### 一条贯穿全局的设计红线

> **LLM 只负责「理解与抽取」，代码负责「统计与排名」。**

绝不让大模型直接输出排行榜 —— 那是幻觉重灾区，既不可复现也无法审计。
所有呈现在用户面前的数字，都由 `app/analytics/` 中的确定性代码从结构化结果里算出，
因此**可以被单元测试完整覆盖**，也因此在同一批数据上永远得到同一个答案。

### 四个值得展开的设计决策

**1. 每条抽取出的技能都必须带 `evidence`（原文证据句）**

```
{ "name": "C++", "required": true, "evidence": "熟练掌握C++与Python，具备良好的工程实现能力" }
```

这不只是「多存一个字段」。它让产品可以做到**任意数字点回原文**，
把「信任」设计进交互里，而不是靠一句免责声明。它也使得幻觉可被度量：
evidence 不在原文中的抽取，可以直接判定为错误。

**2. 缓存不是性能优化，是产品正确性的一部分**

分析类产品必须可复现：同一个输入，今天和明天跑出来应当一致。
把缓存当「优化」，团队就会容忍随机性；把它当正确性约束，
`temperature=0` + 缓存命中就是一条硬规则。

缓存键 = `sha256(kind | prompt版本 | 词表指纹 | 模型 | 输入文本)`。
改 Prompt、换模型、甚至只是改了技能词表，缓存都会自然失效 ——
不会出现「我明明改了，怎么结果没变」这种几乎无法排查的幽灵问题。

**3. 采集层是可插拔的 Protocol，且默认不开启真实站点**

招聘网站随时可能改版、加验证码、封 IP，合规风险也不可控。
把采集收敛到统一接口（`app/sources/base.py`）之后，任何单一来源失效都不影响分析能力。

当前提供多个可组合实现：

| 实现 | 用途 | 状态 |
|---|---|---|
| `SampleSource` | 合成数据，仅供测试与开发回归 | ✅ 产品路径默认关闭 |
| `ManualPasteSource` | 用户自己粘贴 JD 文本 | ✅ 可用 |
| `NowcoderSource` | 牛客公开 sitemap + 岗位详情（不访问 `/search`） | ✅ M4 第一阶段可用 |
| `NcssSource` | 国家大学生就业服务平台公开列表接口 + 详情页 | ✅ 默认启用 |
| `ShixisengSource` | 实习僧公开搜索页 + 详情页 | ✅ 默认启用 |
| `JobicySource` | 无密钥公共招聘 API，保留真实岗位链接并缓存 | ✅ 默认启用 |
| `ArbeitnowSource` | 公共招聘 API，缓存约 975 条近期索引 | ✅ 默认启用 |
| `GreenhouseJobSource` | 企业官方 Greenhouse 招聘板公开 GET API | ✅ 默认启用 5 个公司板 |
| `BraveJobSearchSource` | 通用联网搜索招聘站和企业官网 | ✅ 配置 API Key 后启用 |
| `PublicJobPageSource` | 用户提供的任意公开 HTTPS 岗位页 | ✅ 可用 |

**4. 自由文本必须收敛为规范值（真实模型路径的生死线）**

mock 返回的技能名来自词表，天生规范 —— 所以「不收敛」的缺陷在 mock 路径下
完全看不出来。真模型返回的却是：

```
技能  "PID控制算法" / "团队协作意识" / "嵌入式开发与单片机移植"
学历  "硕士及以上学历" / "本科及以上学历"
经验  "3年以上SLAM相关研发经验"
```

不做收敛，一次分析能抽出 **97 个「不同」技能**（mock 路径只有 36 个），学历被拆成三行，
排行榜与缺口清单同时失效。所以 `orchestrator._canonicalize()` 必须发生在聚合之前：

- 命中一个词条 → 替换（`PID控制算法` → `PID控制`）
- 命中多个词条 → **拆分**（`嵌入式开发与单片机移植` → `嵌入式开发` + `单片机`）

---

## 目录结构

```
job-skill-radar/
├── PLAN.md                     # 完整项目规划书（架构 / 数据模型 / API / 里程碑 / 风险）
├── .env.example
└── backend/
    ├── app/
    │   ├── config.py           # 配置（零依赖的 .env 解析）
    │   ├── cli.py              # 命令行入口（analyze / doctor / serve / directions）
    │   ├── server.py           # HTTP 服务入口（uvicorn app.server:app）
    │   ├── report.py           # 报告渲染（控制台 + JSON）
    │   ├── api/                # ★ HTTP 层：只做契约、校验与错误映射
    │   │   ├── app.py          #   create_app（刻意不建全局实例，避免测试互相污染）
    │   │   ├── schemas.py      #   请求/响应模型
    │   │   ├── deps.py         #   依赖注入（全部走 app.state）
    │   │   ├── errors.py       #   统一错误契约
    │   │   └── routes/         #   meta / analyze / data
    │   ├── analytics/          # ★ 统计层：纯函数，不碰网络
    │   │   ├── lexicon.py      #   技能词表与边界安全匹配
    │   │   ├── normalizer.py   #   技能名归一化（含复合名拆分、别名自学习）
    │   │   ├── canonical.py    #   学历/经验/专业等结构化字段的收敛
    │   │   ├── aggregator.py   #   聚合排名（全项目唯一允许「数数」的地方）
    │   │   └── gap.py          #   技能缺口分析
    │   ├── llm/
    │   │   ├── base.py         #   Provider 契约
    │   │   ├── openai_provider.py  # OpenAI 兼容端点（标准库 urllib 实现）
    │   │   ├── mock_provider.py    # 本地规则引擎（离线可用）
    │   │   ├── extractor.py    #   Prompt 组装 + 缓存 + 校验
    │   │   ├── schemas.py      # ★ 输出契约（校验失败的字段一律丢弃）
    │   │   └── prompts/        #   所有 Prompt 集中管理并版本化
    │   ├── sources/            # 采集层（可插拔）
    │   ├── services/           # 编排 / 缓存 / 后台任务 / 看板读回
    │   │   ├── orchestrator.py #   流程编排 + 进度事件
    │   │   ├── tasks.py        #   后台任务与 SSE 事件流
    │   │   └── dashboard.py    #   从数据库读回一次分析
    │   ├── models/             # 数据模型与 SQLite 访问（含轻量迁移）
    │   └── utils/
    ├── data/
    │   ├── skill_alias.json    # ★ 技能别名表：单一事实来源
    │   └── samples/            # 内置样例 JD 数据集
    ├── tests/                  # 287 个测试
    └── tools/
        ├── check_reproducible.py   # 结果可复现性门禁
        └── smoke_api.py            # HTTP 冒烟测试（真实网络栈 + SSE）
frontend/                       # M3：React + Vite + TypeScript 看板
    ├── src/
    │   ├── api/                #   types.ts（后端契约）/ client.ts / hooks.ts
    │   ├── components/         #   charts/ · SkillDrawer · Layout · ui
    │   ├── pages/              #   录入 / 进度 / 看板 / 岗位 / 历史 + 组件回归测试
    │   ├── test/               #   Vitest / Testing Library 测试环境
    │   ├── store/              #   zustand（只放前端本地状态）
    │   └── utils/highlight.ts  #   证据句定位与高亮
    └── dist/                   #   构建产物（后端在它存在时自动托管）
```

回归验证：后端执行 `cd backend && python -m pytest -q`（287 项）；前端执行
`cd frontend && npm test`。前端首批用例覆盖无样本方向、空会话与图表异常隔离。

---

## 指标口径（看懂报告的关键）

| 指标 | 定义 | 回答什么问题 |
|---|---|---|
| `count` | 提到该技能的 JD 条数 | 「有多少岗位要它」 |
| `coverage` | `count / 样本总数` | 普及度（消除样本量差异，比绝对次数公平） |
| `required_ratio` | 标为硬性要求的占比 | 「不学行不行」 |
| `weighted_score` | `硬性要求数 × 1.0 + 加分项数 × 0.4` | 综合排序依据 |

缺口分档规则（阈值集中在 `app/analytics/gap.py`，可按真实数据校准）：

- **必学**：`coverage ≥ 40%` 且 `required_ratio ≥ 60%`
- **建议学**：`coverage ≥ 20%` 或 `required_ratio ≥ 40%`
- **加分项**：其余

另有一道**噪音闸门**：只被 1 个岗位提到的技能，无论在那个岗位里多硬性，
一律落到加分项。没有它，真实大模型的细粒度抽取会让「建议学」从 31 项膨胀到 97 项，
清单直接失去指导意义。

另有一个 `coverage_score`：你的技能覆盖了市场多少**要求权重**。
它比「数技能个数」更贴近现实 —— 覆盖一个高覆盖率的必学技能，
和覆盖一个冷门加分项，价值完全不同。

---

## 测试

```bash
cd backend
python -m pytest -q
```

覆盖的重点：

- **词表边界安全**：`C` 不能匹配到 `C++`，`SQL` 不能匹配到 `MySQL`，
  `EtherCAT` 不能算成 `CAN总线`（这类 bug 不报错，只会悄悄污染统计结果）
- **归一化收敛**：`python3` / `Python编程` / `PYTHON` 必须收敛为同一项
- **自由文本收敛**：用桩 provider 模拟真模型的复合名/修饰名输出
- **聚合正确性**：条数、覆盖率、加权分、同岗位内去重、必须项优先
- **缺口分档**：集合运算、优先级排序、单次出现的噪音闸门
- **evidence 不变量**：每条技能的 evidence 必须是原文子串
- **端到端可复现**：冷启动与热缓存两次运行结果必须完全一致
- **API 契约**：错误码、SSE 与轮询一致、看板从数据库读回
- **schema 迁移**：旧库必须能补列成功启动，而不是崩在「no such column」
- **前端托管**：SPA 深链回落、`/api/*` 不被 fallback 吃掉、目录穿越被拒绝
- **脱敏**：明文不落库、幂等、evidence 仍可回溯、24 条样例 JD 一字不改
- **别名闭环**：写回 json 后归一化真的变了、缓存自动失效、文件排版逐字节不变
- **报告导出**：与看板接口同源、表格里的竖线被正确转义

前端的类型契约用 `npm run typecheck` 兜住（后端不为分析结果建模型，
所以 `src/api/types.ts` 是唯一声明这份契约的地方）。

---

## 数据来源与合规

本仓库自带的 JD 样例是**基于公开岗位描述重写的合成数据**，不含真实公司信息，
仅用于演示与回归测试。

关于真实站点采集，请务必阅读 `PLAN.md` 第 9 节。三条底线：

1. **不默认开启**真实站点采集（`JOBRADAR_ENABLE_LIVE_SOURCES=0`）；
2. 严格限流、遵守 `robots.txt`，优先使用「用户手动粘贴 JD」这条零风险路径；
3. 抓取到的数据仅本地存储、仅个人学习研究用途，不对外分发。

启用方式：在 `.env` 中设置 `JOBRADAR_ENABLE_LIVE_SOURCES=1` 后重启后端。
前端只使用真实岗位源；内置样例已从产品路径关闭。首次查询会建立
`backend/data/live_cache/` 索引，因此较慢；
后续查询优先命中本地缓存。牛客 `robots.txt` 禁止 `/search`，本项目不会访问该路径，
所以召回范围以公开 sitemap 当前列出的岗位为准，不能把 0 条误解成市场上没有岗位。

实际职位现在有六条入口：

1. **自动在线检索**：整次分析共享 `JOBRADAR_LIVE_SOURCE_BUDGET`（默认 90 秒）预算，
   扫描过程持续推送进度，并可在分析页取消；
2. **国内公开岗位源**：自动检索国家大学生就业服务平台、实习僧和牛客，结果保留可直接打开的原始岗位链接；
3. **直接粘贴岗位 URL**：支持牛客、实习僧、智联、前程无忧等公开详情和企业招聘页；优先读取标准
   Schema.org `JobPosting`，没有结构化数据时才降级到可读正文；
4. **Brave Search API（可选）**：配置服务端 `BRAVE_SEARCH_API_KEY` 后，通过官方搜索 API
   补足 sitemap 的长尾召回；密钥不进入浏览器或数据库。
5. **Jobicy 公共招聘 API**：无需密钥，按英文岗位词检索国际/远程职位，保留原站链接，
   相同查询缓存一小时；
6. **企业招聘官网**：读取配置在 `JOBRADAR_GREENHOUSE_BOARDS` 中的企业公开招聘板，
   默认包括 Figma、Discord、Airbnb、Roblox、Pinterest；先匹配岗位标题，再读取 JD 详情。

当前产品地域固定为 `JOBRADAR_TARGET_MARKET=cn_mainland`：自动来源只有明确标注中国大陆
城市的岗位才会进入分析；香港、澳门、台湾、Worldwide 及海外 Remote 岗位会被后端过滤。

另外，JD 正文里的联系方式（手机号 / 邮箱 / 身份证 / 微信）会在**入库与抽取之前**
被自动脱敏，明文既不落库也不发给模型。详见上文「个人信息脱敏」。

---

## 当前进度

- ✅ **M1 地基与最小闭环**：配置、数据模型、Provider 抽象、抽取模块、
  采集层、归一化与收敛层、聚合与缺口分析、CLI、环境自检 `doctor`、样例数据集
- ✅ **M2 后端 API**：FastAPI 全套路由、SSE 进度推送、后台任务管理、
  看板从数据库读回、统一错误契约、轻量 schema 迁移
- ✅ **M3 可视化看板**：React + Vite + TS，条形排行 / 热力图 / 雷达图 / 缺口泳道，
  点任意技能回溯原始 JD 与证据句；构建产物由后端托管，生产环境单端口
- ✅ **M5 第一阶段**：JD 个人信息脱敏、技能别名自学习闭环（`alias`）、
  Markdown 报告导出（`report`）
- ✅ **M4 多源采集**：牛客 sitemap、Jobicy、企业官方 Greenhouse、可选 Brave 全网搜索、
  公开岗位 URL 导入、跨源去重与公平时间预算
- ⏳ **M5 其余**：技能趋势曲线、学习路径生成、多城市对比

详见 `PLAN.md` 第 10 节。

---

## 常见问题

**中文输出乱码？**
CLI 会主动把 stdout 切到 UTF-8。若你的终端仍显示乱码，先执行 `chcp 65001`，
或设置环境变量 `PYTHONIOENCODING=utf-8`。

**要装依赖吗？**
M1 核心链路零第三方依赖。只有接入真实大模型时才需要网络能力
（且实现用的是标准库 `urllib`，连 `httpx` 都不需要）。
M2 的 HTTP 层需要 `fastapi` + `uvicorn`，用 `pip install -e ".[api]"` 安装。

**配好了 Key 但报错？**
先跑 `python -m app.cli doctor`。它会区分四类故障：
Key 无效/过期、余额不足、`base_url` 写错、**模型名不在端点支持的列表里**
（最后这类最常见的表现只是一句含糊的 400，doctor 会直接把可选模型名打出来）。

**报告里出现了词表没见过的技能？**
属正常现象，说明它在 `skill_alias.json` 里还没有条目。系统会把它以「自身为规范名」
登记进 SQLite 的 `skill_alias` 表（`source=learned`），词表随使用逐渐变准。
要把它合并到某个规范名，在 `data/skill_alias.json` 里加一条别名即可
（改完缓存会自动失效，不需要手动清库）。

**打开 8000 端口只看到 JSON，没有看板？**
说明前端还没构建。`cd frontend && npm install && npm run build` 后重启服务即可。
（`python -m app.cli serve` 启动时会直接告诉你当前是哪种状态。）
