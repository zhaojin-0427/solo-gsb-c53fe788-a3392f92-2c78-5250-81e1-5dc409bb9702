# 广告播出核销 Web 应用

单频道广告计划与实播日志的自动核销系统：用 **OR-Tools CP-SAT** 在全局范围内为各广告位
分配实播片段，依次最大化核销位数、最小化首播起点偏差总和，并在同分时给出
**字典序唯一**的方案；每次计算保存包含**分配证据与输入快照的不可变报告**。

技术栈：Python 3.11 · FastAPI · SQLite · OR-Tools（CP-SAT）· 原生 JavaScript（零前端依赖）。

---

## 一、启动方式（Docker Compose 一键启动）

```bash
docker compose up --build -d
```

启动后访问：

- **应用界面**：<http://localhost:8000/>
- **接口文档（Swagger UI）**：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/health>

停止：

```bash
docker compose down          # 保留报告数据（Docker volume）
docker compose down -v       # 同时删除报告数据卷
```

报告数据库持久化在命名卷 `verify-data`（容器内 `/data/reports.db`）。

### 不使用 Docker（本地开发）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

可用环境变量 `APP_DB_PATH` 指定数据库路径（默认 `app/data/reports.db`）。

---

## 二、核销规则

所有时间均为**整数毫秒**，所有区间均为**半开区间** `[start, end)`。

### 输入

- **广告位（计划）** `slots[]`
  | 字段 | 含义 |
  | --- | --- |
  | `id` | 广告位唯一 ID |
  | `material_id` | 素材 ID |
  | `planned_start` | 计划起点（非负整数） |
  | `duration` | 正整数时长 |
  | `tolerance` | 首片段起点容差（非负） |
  | `max_gap` | 相邻片段最大停顿（非负） |

- **实播片段（日志）** `fragments[]`
  | 字段 | 含义 |
  | --- | --- |
  | `id` | 片段唯一 ID |
  | `material_id` | 素材 ID |
  | `on_air_start` / `on_air_end` | 播出半开区间 |
  | `source_start` / `source_end` | 素材源半开区间 |

  播出区间与素材源区间长度必须**相等且大于零**。

### 核销条件

广告位被核销，当且仅当存在一个片段序列满足：

1. **同素材**：序列中每个片段的 `material_id` 与广告位一致；
2. **源拼满**：片段的素材源区间无重叠、无缺口，恰好拼成 `[0, duration)`；
3. **顺序一致**：播出顺序与素材源顺序一致，相邻播出片段互不重叠，
   且停顿 `next.on_air_start - prev.on_air_end ∈ [0, max_gap]`；
4. **容差**：首片段播出起点在 `planned_start ± tolerance` 内；
5. **不复用**：同一片段不得分配给多个广告位，也不得在一个位中重复使用。

### 优化目标（按优先级，全局分配）

1. 最大化核销广告位**位数**；
2. 在位数最优的方案中，最小化全部核销位
   `|首片段播出起点 − planned_start|` 的**总和**；
3. 仍同分时，取 **（已核销位 ID 列表，各广告位片段 ID 序列）字典序最小**的方案
   （位按输入顺序、片段序列按素材源顺序比较）。

第 1、2 级目标用加权目标一次求出，第 3 级通过枚举全部 `(位数, 偏差和)`
最优解在 Python 侧裁决。

---

## 三、界面与使用

首页共四个区域：

1. **输入数据**：直接编辑 JSON（点「载入示例」可加载内置样例），点「核销计算」；
   校验失败时会列出全部字段级错误。
2. **已保存报告**：按时间倒序列出历史报告；点击任一行即可回看该报告。
   输入修改并重算后，**旧报告不会被覆盖或删除**，仍可随时打开查看（页面顶部出现
   「正在查看历史报告」提示条）。
3. **时间轴对照**：计划时间轴（绿色=已核销，红色=未核销，蓝色虚线窗=容差窗）
   与实播时间轴（蓝色=已分配片段，灰斜纹=闲置片段，白线=相邻片段停顿点）并排展示，
   鼠标悬停可见完整区间信息。
4. **核销证据与剩余项**：
   - 每个已核销广告位给出**完整证据链**：片段 ID、各片段的素材源区间/播出区间、
     相邻停顿、首播偏差；
   - 未核销广告位及诊断原因；
   - 闲置实播片段列表。

---

## 四、HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/sample` | 内置示例数据 |
| POST | `/api/verify` | 校验并核销；成功后写入不可变报告 |
| GET | `/api/reports` | 报告列表（含最新标记与统计） |
| GET | `/api/reports/{id}` | 报告详情（含输入快照 `input` 与结果 `result`） |

`POST /api/verify` 请求体即输入 JSON；输入不合法返回 `422`，`detail.errors`
为全部错误信息。报告 ID 为 32 位十六进制 UUID，报告内容只增不改。

---

## 五、项目结构

```
.
├── app/
│   ├── main.py          # FastAPI 入口 / API
│   ├── schemas.py       # 输入校验（半开区间、长度相等、唯一 ID 等）
│   ├── solver.py        # CP-SAT 全局分配模型与字典序裁决
│   ├── store.py         # SQLite 不可变报告存储
│   └── static/          # 原生 JS 前端（index.html / app.js / styles.css）
├── tests/
│   └── test_scenarios.py# 求解器 14 组场景（26 项断言）
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

运行测试：

```bash
python3 tests/test_scenarios.py
```
