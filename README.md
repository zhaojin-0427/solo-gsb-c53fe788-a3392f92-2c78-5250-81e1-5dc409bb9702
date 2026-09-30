# 广告播出核销 Web 应用

单频道广告**计划广告位**与**实播日志**的核销与证据管理：导入计划与实播数据后，
用 OR-Tools CP-SAT 做全局最优分配（自动处理**重复素材**与**交错片段**竞争），
并排展示两条时间轴，列出未核销位与闲置片段，并可保存含**输入快照 + 分配证据**的
不可变报告；输入修改、重新计算后，旧报告仍可随时查看。

- 后端：Python 3.11 · FastAPI · SQLite · OR-Tools CP-SAT
- 前端：原生 JavaScript / HTML / CSS（无构建步骤、无外部依赖）
- 部署：Docker / Docker Compose 一键启动

---

## 一、快速启动（Docker Compose）

```bash
docker compose up --build -d
```

启动后浏览器访问：

- **应用界面**：http://localhost:8000
- API 文档（Swagger）：http://localhost:8000/docs

首次启动会自动建库并载入一份内置示例（4 个广告位、13 个实播片段，覆盖重复素材、
交错片段、容差命中、停顿超限、闲置片段等情形）。

数据持久化在宿主机 `./data/app.db`（容器内 `/data`，见 `docker-compose.yml` 的卷挂载）。

停止：

```bash
docker compose down        # 停止并移除容器（数据库保留在 ./data）
```

修改端口：编辑 `docker-compose.yml` 中 `"8000:8000"`，例如 `"18000:8000"` 后重新启动。

### 不用 Docker 时的本地运行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## 二、数据格式（整数毫秒，区间均为左闭右开 `[start, end)`）

在界面点击 **“导入计划 / 日志”**，粘贴如下 JSON（点击“填入示例”可载入样例）：

```json
{
  "slots": [
    {
      "id": "S001",                  // 广告位唯一 ID
      "material_id": "M01",          // 素材 ID
      "planned_start": 5000,         // 计划起点（整数毫秒）
      "duration": 3000,              // 正整数时长（毫秒）
      "tolerance": 250,              // 非负起点容差
      "max_pause": 500               // 非负最大停顿
    }
  ],
  "segments": [
    {
      "id": "L001",                  // 实播记录唯一 ID
      "material_id": "M01",          // 素材 ID
      "air_start": 4950, "air_end": 6150,   // 播出半开区间
      "src_start": 0,    "src_end": 1200    // 素材源半开区间
    }
  ]
}
```

校验规则（不满足时界面逐行列出中文错误，导入不会落库）：

- 广告位 ID、实播记录 ID 在各自集合内唯一且非空；
- `duration` 为正整数，`tolerance` / `max_pause` 为非负整数；
- 时间字段必须是严格整数（布尔值不接受）；
- 播出区间与素材源区间长度都必须 **大于 0**，且两者长度 **相等**。

导入为**整量替换**当前工作集；历史报告不受影响。

---

## 三、核销规则

广告位被核销，当且仅当存在一组**同素材**片段，使以下条件同时成立；所有片段在
全部广告位之间全局互斥（**片段不得复用**）：

1. **源区间拼满**：各片段源区间无重叠、无缺口，恰好覆盖 `[0, duration)`；
2. **顺序一致**：片段的播出顺序与源顺序一致（相邻片段播出区间不重叠，
   即 `下一播出起点 ≥ 上一播出终点`）；
3. **停顿约束**：相邻片段播出间隔
   `0 ≤ air_start[下] − air_end[上] ≤ max_pause`；
4. **首片段容差**：首片段源起点为 0，且
   `|air_start[首] − planned_start| ≤ tolerance`。

### 优化目标（存在重复素材 / 交错片段竞争时的全局分配）

按以下顺序逐字典序优化：

1. **最大化核销位数**；
2. 在位数相同的方案中，**最小化各广告位首片段播出起点偏差之和**
   （`Σ |首播起点 − 计划起点|`，整数毫秒绝对值）；
3. 仍同分时依次取：
   - **已核销广告位 ID 升序列表字典序最小**的方案；
   - 再按广告位 ID 升序，逐一取其**片段 ID 序列字典序最小**
     （序列前缀相同即终止时，较短序列更小；字符串按 Unicode 码点序比较）。

实现方式：CP-SAT 中为每个广告位在其素材片段上建立
`首片段 → 拼接边 → 末片段` 的流路径模型（源端点相接 + 播出停顿约束），
叠加片段全局互斥；前两层用线性目标求解，平局判定通过分层贪心 + 可行性求解完成。

---

## 四、界面说明

- 顶部统计卡：核销位数、未核销位数、闲置片段数、偏差总和等；
- **两条时间轴并排**：左侧计划广告位（绿=已核销，红=未核销，悬停可见容差/停顿），
  右侧实播片段（蓝=已被使用，灰=闲置，浅灰=素材无对应广告位）；相交条目自动分泳道；
- **未核销广告位**表：给出诊断原因（无满足容差的首片段 / 无法无缺口拼满或停顿超限 /
  独立可行但全局未入选）；
- **闲置片段**表：未被任何核销位使用的片段及原因；
- **核销分配证据**：每个核销位展示 `广告位 → 片段…` 链、首播偏差，以及
  素材一致、源拼满、播出顺序、停顿明细、容差命中的逐项核对，可展开完整 JSON；
- **保存核销报告**：固化当前工作集快照与分配证据（含 SHA-256 指纹）；
  点击报告列表中的任意报告即可查看，页面顶部黄色横幅提示“正在查看历史报告”；
  报告只增不改，导入新数据并重算后旧报告依然存在、可查、可下载 JSON。

---

## 五、HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/state` | 当前工作集 + 实时分配结果 |
| POST | `/api/import` | 校验并整量替换计划/日志，返回重算结果（422 返回逐行错误） |
| POST | `/api/reports` | 对当前工作集执行分配并保存不可变报告 |
| GET | `/api/reports` | 报告列表（ID、生成时间、指纹） |
| GET | `/api/reports/{id}` | 单个报告完整内容（输入快照 + 结果 + 证据 + 指纹） |

报告结构（节选）：

```json
{
  "id": "R-20260930-121755-17ceb1c4",
  "created_at": "2026-09-30T12:17:55+0000",
  "fingerprint": "17ceb1c4…(sha256 of payload)",
  "input_snapshot": { "slots": [ … ], "segments": [ … ] },
  "result": {
    "verified_count": 3,
    "total_start_deviation_ms": 100,
    "verified_slots": [
      {
        "slot_id": "S001",
        "segment_ids": ["L001", "L002", "L003"],
        "first_air_start": 4950,
        "start_deviation_ms": 50,
        "evidence": {
          "source_intervals": [[0,1200],[1200,2250],[2250,3000]],
          "air_intervals": [[4950,6150],[6150,7200],[7200,7950]],
          "pauses": [{ "from": "L001", "to": "L002", "air_gap_ms": 0 }, …],
          "source_no_gap_no_overlap": true,
          "pauses_within_limit": true,
          "first_start_within_tolerance": true
        }
      }
    ],
    "unverified_slots": [ … ],
    "idle_segments": [ … ],
    "used_segment_ids": [ … ]
  }
}
```

---

## 六、目录结构

```
.
├── app/
│   ├── main.py          # FastAPI 路由 / 静态资源
│   ├── solver.py        # CP-SAT 模型：流路径分配 + 分层目标 + 字典序平局判定
│   ├── validation.py    # 导入校验（整数毫秒 / 等长半开区间 / 唯一 ID）
│   ├── storage.py       # SQLite：工作集整量替换 + 不可变报告
│   ├── sample_data.py   # 内置示例
│   └── static/          # 原生 JS 前端（index.html / app.js / styles.css / sample.json）
├── data/                # SQLite 持久化目录（卷挂载）
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
