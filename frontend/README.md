# RightThing 正事 · 前端看板

React + Vite + TypeScript 的可视化看板，消费 `backend/` 提供的 REST + SSE 接口。

## 快速开始

**开发模式**（有 HMR，改一行立刻看到效果）：

```bash
# 终端 1：后端
cd ../backend && python -m app.cli serve --port 8000

# 终端 2：前端
npm install
npm run dev            # http://localhost:5173
```

Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`（见 `vite.config.ts`），
所以前端代码里只写 `/api/...`，不需要任何 baseURL 配置。
后端已在 `app/api/app.py` 里放行 `localhost:5173` 的 CORS。

**生产模式**（一个端口，用户不需要知道 Vite 的存在）：

```bash
npm install && npm run build     # 产出 frontend/dist
cd ../backend && python -m app.cli serve --port 8000
# 打开 http://127.0.0.1:8000/
```

后端在 `frontend/dist/index.html` 存在时会自动接管根路径（`app/api/static.py`），
并对非 `/api/*` 的未命中路径回落到 SPA 入口 —— 因此 `/sessions/1` 这类前端路由
刷新页面不会 404。

## 脚本

| 命令 | 说明 |
|---|---|
| `npm run dev` | Vite 开发服务器（5173） |
| `npm run build` | 类型检查 + 生产构建到 `dist/` |
| `npm run preview` | 预览构建产物（不含后端） |
| `npm run typecheck` | 只做类型检查 |

## 页面结构

| 路由 | 页面 | 说明 |
|---|---|---|
| `/` | 技能录入 | 输入 → **归一化预览确认** → 启动分析 |
| `/analyze?task=<id>` | 进度 + 方向选择 | SSE 进度时间线、抽取进度条、方向卡片 |
| `/sessions/:id` | 分析看板 | 缺口泳道 / 排行 / 雷达 / 热力图 / 招聘方偏好 |
| `/jobs/:jobId` | 岗位详情 | JD 原文 + 证据高亮 + 幻觉度量 |
| `/history` | 历史分析 | 往期会话列表（后端从数据库读回，不依赖进程内存） |

## 三个不显然的设计点

**1. `src/api/types.ts` 是刻意的「契约复写」**

后端刻意不给分析结果建 Pydantic 模型（见 `backend/app/api/schemas.py` 的注释），
所以前端是唯一持有这份类型的地方。字段名写错在 JS 里只会静默变成 `undefined`，
图表会安静地画成空白 —— 那是最难查的一类 bug。改后端返回结构时**必须同步这里**。

**2. 长任务用「SSE + 轮询」双通道**

`POST /api/analyze` 只返回 `task_id`。进度来自 `GET /api/tasks/{id}/events`（SSE），
但反向代理可能在 30~60 秒无数据时掐断连接，所以同时还每 3 秒轮询一次任务状态
（`useTaskProgress`）。轮询不只是兜底，它还负责**判定任务真的结束了** ——
不让前端靠超时去猜。

**3. 看板数据永远从 `GET /api/sessions/{id}` 读，不进 zustand**

zustand 里只放「用户正在输入什么、选中了哪个方向、当前任务 id」这类真正属于前端的东西。
服务端数据一旦拷进本地 store，就会出现两份真相，也就等于放弃了
「服务重启后历史仍可查」这条后端保证。

## 想改哪里看哪里

```
src/
├── api/
│   ├── types.ts        ← 后端契约（改后端结构先改这里）
│   ├── client.ts       ← fetch 封装 + 统一错误契约 + SSE 订阅
│   └── hooks.ts        ← TanStack Query hooks + useTaskProgress
├── components/
│   ├── charts/         ← 四种图 + useChart（dispose / ResizeObserver）
│   ├── SkillDrawer.tsx ← 点技能 → 回溯原始 JD + 证据高亮
│   ├── Layout.tsx      ← 导航 + 常驻服务健康状态
│   └── ui.tsx          ← 极小的 UI 原语（刻意不引组件库）
├── pages/              ← 五个页面，与上表一一对应
├── store/useWizard.ts  ← 只放前端本地状态
└── utils/highlight.ts  ← 证据句定位（用 indexOf 而非正则拼接）
```

## 为什么没上 shadcn/ui

`PLAN.md` 原本写的是 `tailwindcss + shadcn/ui`。实际实现只用了 Tailwind，
UI 原语手写在 `components/ui.tsx` 里：这个看板需要的组件只有卡片、按钮、
徽章、进度条这几种，引入一整套设计系统 + CLI 生成器，收益抵不过依赖成本 ——
与后端「有意不引入 SQLModel / structlog」是同一个判断。
