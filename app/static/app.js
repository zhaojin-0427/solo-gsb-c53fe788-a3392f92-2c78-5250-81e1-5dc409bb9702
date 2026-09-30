// 广告播出核销前端（原生 JS）
const $ = (id) => document.getElementById(id);

let view = null;       // 当前渲染数据 { slots, segments, result, report }
let reportsCache = [];

// ---------- 工具 ----------
const fmt = (n) => Number(n).toLocaleString("en-US");
const intervalText = (a, b) => `[${fmt(a)}, ${fmt(b)}) · ${fmt(b - a)} ms`;
const esc = (s) => String(s); // 统一使用 textContent，避免 HTML 注入

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("data-")) node.setAttribute(k, v);
    else node[k] = v;
  }
  for (const c of [].concat(children)) if (c != null) node.appendChild(c);
  return node;
}

function toast(msg, ms = 2600) {
  const t = el("div", { class: "toast", text: msg });
  document.body.appendChild(t);
  setTimeout(() => t.remove(), ms);
}

// ---------- 数据加载 ----------
async function loadCurrent() {
  const r = await fetch("/api/state");
  view = await r.json();
  view.report = null;
  render();
}

async function loadReports() {
  reportsCache = await (await fetch("/api/reports")).json();
  renderReports();
}

async function openReport(id) {
  const r = await fetch(`/api/reports/${encodeURIComponent(id)}`);
  const report = await r.json();
  view = { ...report.input_snapshot, result: report.result, report };
  render();
}

// ---------- 时间轴 ----------
function domainOf(slots, segments) {
  const pts = [];
  for (const s of slots) {
    pts.push(s.planned_start, s.planned_start + s.duration,
      s.planned_start - s.tolerance, s.planned_start + s.tolerance);
  }
  for (const g of segments) pts.push(g.air_start, g.air_end);
  if (!pts.length) return { min: 0, max: 1 };
  const min = Math.min(...pts), max = Math.max(...pts);
  return { min, max: max > min ? max : min + 1 };
}

// 贪心分层：相交条目放到不同泳道
function packLanes(items) {
  const lanes = []; // 每条泳道记录最后结束点
  const placed = [];
  for (const it of items) {
    let lane = lanes.findIndex((end) => it.start >= end);
    if (lane === -1) { lanes.push(it.end); lane = lanes.length - 1; }
    else lanes[lane] = it.end;
    placed.push({ ...it, lane });
  }
  return { placed, laneCount: Math.max(1, lanes.length) };
}

function renderTimeline(container, domain, items, barClassFn, tipFn, labelFn) {
  container.textContent = "";
  const span = domain.max - domain.min;
  const ruler = el("div", { class: "ruler" });
  for (let i = 0; i <= 10; i++) {
    ruler.appendChild(el("span", { text: fmt(Math.round(domain.min + span * i / 10)) }));
  }
  container.appendChild(ruler);

  const sorted = items.slice().sort((a, b) => a.start - b.start || a.end - b.end);
  const { placed, laneCount } = packLanes(sorted);
  const wrap = el("div", { class: "lane-wrap" });
  wrap.style.minHeight = `${laneCount * 32 + 10}px`;
  for (const it of placed) {
    const left = (it.start - domain.min) / span * 100;
    const width = Math.max((it.end - it.start) / span * 100, 0.4);
    const bar = el("div", { class: `bar ${barClassFn(it)}`, title: tipFn(it) },
      el("span", { class: "bar-label", text: labelFn(it) }));
    bar.style.left = left + "%";
    bar.style.width = width + "%";
    bar.style.top = (it.lane * 32 + 5) + "px";
    wrap.appendChild(bar);
  }
  container.appendChild(wrap);
}

// ---------- 汇总 / 图例 ----------
function renderSummary() {
  const { result } = view;
  const box = $("summary");
  box.textContent = "";
  const stats = [
    [result.verified_count, "核销广告位数", "good"],
    [result.unverified_slots.length, "未核销广告位", "bad"],
    [result.idle_segments.length, "闲置片段", "warn"],
    [fmt(result.total_start_deviation_ms), "首播起点偏差总和 (ms)", ""],
    [view.segments.length, "实播片段总数", ""],
  ];
  for (const [num, lbl, cls] of stats) {
    box.appendChild(el("div", { class: "stat" }, [
      el("div", { class: `num ${cls}`, text: String(num) }),
      el("div", { class: "lbl", text: lbl }),
    ]));
  }
}

function renderLegend() {
  const box = $("legend");
  box.textContent = "";
  for (const [color, text] of [
    ["#16a34a", "计划：已核销"], ["#ef4444", "计划：未核销"],
    ["#2563eb", "实播：已被核销使用"], ["#94a3b8", "实播：闲置"],
    ["#cbd5e1", "实播：素材无对应广告位"],
  ]) {
    box.appendChild(el("span", {}, [el("span", { class: "sw", style: `background:${color}` }), text]));
  }
}

// ---------- 未核销 / 闲置表格 ----------
function renderUnverified() {
  const box = $("unverified");
  box.textContent = "";
  if (!view.result.unverified_slots.length) {
    box.appendChild(el("p", { text: "无未核销广告位。" }));
    return;
  }
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {}, ["ID", "素材", "计划起点", "时长", "容差", "最大停顿", "原因"]
    .map((t) => el("th", { text: t })))));
  const tb = el("tbody");
  for (const s of view.result.unverified_slots) {
    tb.appendChild(el("tr", {}, [
      el("td", { class: "mono", text: s.slot_id }),
      el("td", { class: "mono", text: s.material_id }),
      el("td", { text: fmt(s.planned_start) }),
      el("td", { text: fmt(s.duration) }),
      el("td", { text: fmt(s.tolerance) }),
      el("td", { text: fmt(s.max_pause) }),
      el("td", { text: s.reason }),
    ]));
  }
  table.appendChild(tb);
  box.appendChild(table);
}

function renderIdle() {
  const box = $("idle");
  box.textContent = "";
  if (!view.result.idle_segments.length) {
    box.appendChild(el("p", { text: "无闲置片段。" }));
    return;
  }
  const table = el("table");
  table.appendChild(el("thead", {}, el("tr", {}, ["片段 ID", "素材", "播出区间", "源区间", "说明"]
    .map((t) => el("th", { text: t })))));
  const tb = el("tbody");
  for (const g of view.result.idle_segments) {
    tb.appendChild(el("tr", {}, [
      el("td", { class: "mono", text: g.seg_id }),
      el("td", { class: "mono", text: g.material_id }),
      el("td", { class: "mono", text: intervalText(g.air_start, g.air_end) }),
      el("td", { class: "mono", text: intervalText(g.src_start, g.src_end) }),
      el("td", { text: g.reason }),
    ]));
  }
  table.appendChild(tb);
  box.appendChild(table);
}

// ---------- 分配证据 ----------
function checkRow(label, ok, detail) {
  return el("div", { class: ok ? "ok" : "bad" },
    `${label}${detail ? "：" + detail : ""}`);
}

function renderEvidence() {
  const box = $("evidence");
  box.textContent = "";
  const list = view.result.verified_slots;
  if (!list.length) {
    box.appendChild(el("p", { text: "本次分配无核销广告位。" }));
    return;
  }
  for (const s of list) {
    const e = s.evidence;
    const head = el("div", { class: "ev-head" }, [
      el("span", { class: "tag ok", text: "已核销" }),
      el("strong", { class: "mono", text: s.slot_id }),
      el("span", { class: "mono", text: `素材 ${s.material_id}` }),
      el("span", { class: "ev-chain", text: `${s.slot_id} → ${s.segment_ids.join(" → ")}` }),
      el("span", { text: `首片段起点 ${fmt(s.first_air_start)} ms（偏差 ${fmt(s.start_deviation_ms)} ms）` }),
    ]);
    const checks = el("div", { class: "checks" }, [
      checkRow("素材一致", e.material_consistent),
      checkRow("首片段起点在 ±容差内", e.first_start_within_tolerance,
        `[${fmt(s.planned_start - s.tolerance)}, ${fmt(s.planned_start + s.tolerance)}]`),
      checkRow("源区间无重叠无缺口拼满 [0, 时长)", e.source_no_gap_no_overlap,
        e.source_intervals.map(([a, b]) => `[${fmt(a)},${fmt(b)})`).join(" ")),
      checkRow("播出同序且相邻不重叠", e.air_order_consistent),
      checkRow("相邻停顿均 ≤ 最大停顿", e.pauses_within_limit,
        e.pauses.length ? e.pauses.map((p) => `${fmt(p.air_gap_ms)}ms`).join(" / ") : "单片段，无相邻停顿"),
    ]);
    const more = el("details", {}, [
      el("summary", { text: "完整证据（区间、停顿明细）" }),
      el("pre", { text: JSON.stringify(s, null, 2) }),
    ]);
    box.appendChild(el("div", { class: "ev-card" }, [head, checks, more]));
  }
}

// ---------- 报告 ----------
function renderReports() {
  const box = $("reports");
  box.textContent = "";
  if (!reportsCache.length) {
    box.appendChild(el("p", { text: "尚无报告。点击“保存核销报告”生成（输入快照与分配证据一并固化）。" }));
    return;
  }
  for (const r of reportsCache) {
    const isOpen = view.report && view.report.id === r.id;
    const row = el("div", { class: "report-row" }, [
      el("span", { class: "tag ok", text: isOpen ? "查看中" : "报告" }),
      el("a", {
        class: "rid", href: "#", text: r.id,
        onclick: (ev) => { ev.preventDefault(); openReport(r.id); },
      }),
      el("span", { class: "meta", text: `生成于 ${r.created_at} · SHA-256 ${r.fingerprint.slice(0, 16)}…` }),
    ]);
    box.appendChild(row);
  }
}

// ---------- 整体渲染 ----------
function render() {
  const { slots, segments, result } = view;
  const verifiedIds = new Set(result.verified_slots.map((s) => s.slot_id));
  const usedSegIds = new Set(result.used_segment_ids);
  const referencedMats = new Set(slots.map((s) => s.material_id));
  const domain = domainOf(slots, segments);

  renderSummary();
  renderLegend();

  renderTimeline(
    $("plan-timeline"), domain,
    slots.map((s) => ({ start: s.planned_start, end: s.planned_start + s.duration, raw: s })),
    (it) => verifiedIds.has(it.raw.slot_id) ? "verified" : "unverified",
    (it) => {
      const s = it.raw;
      return `${s.slot_id} · 素材 ${s.material_id}\n计划区间 ${intervalText(s.planned_start, s.planned_start + s.duration)}\n容差 ±${fmt(s.tolerance)} ms · 最大停顿 ${fmt(s.max_pause)} ms\n状态：${verifiedIds.has(s.slot_id) ? "已核销" : "未核销"}`;
    },
    (it) => `${it.raw.slot_id} · ${it.raw.material_id}`,
  );

  renderTimeline(
    $("air-timeline"), domain,
    segments.map((g) => ({ start: g.air_start, end: g.air_end, raw: g })),
    (it) => {
      const g = it.raw;
      if (!usedSegIds.has(g.seg_id)) return referencedMats.has(g.material_id) ? "seg-idle" : "seg-idle mismatch";
      return "seg-used";
    },
    (it) => {
      const g = it.raw;
      const state = usedSegIds.has(g.seg_id) ? "已被核销使用" : "闲置";
      return `${g.seg_id} · 素材 ${g.material_id}\n播出 ${intervalText(g.air_start, g.air_end)}\n源   ${intervalText(g.src_start, g.src_end)}\n状态：${state}`;
    },
    (it) => `${it.raw.seg_id}`,
  );

  renderUnverified();
  renderIdle();
  renderEvidence();
  renderReports();

  // 报告横幅
  const banner = $("report-banner");
  if (view.report) {
    banner.classList.remove("hidden");
    $("report-banner-text").textContent =
      `正在查看不可变报告 ${view.report.id}（生成于 ${view.report.created_date || view.report.created_at}）。下方为当时的输入快照与分配证据，不代表当前工作集。`;
  } else {
    banner.classList.add("hidden");
  }
}

// ---------- 事件 ----------
$("btn-refresh").onclick = () => loadCurrent().then(() => toast("已重算")).catch((e) => toast("刷新失败：" + e));
$("btn-back-current").onclick = () => loadCurrent();
$("btn-download-report").onclick = () => {
  if (!view.report) return;
  const blob = new Blob([JSON.stringify(view.report, null, 2)], { type: "application/json" });
  const a = el("a", { href: URL.createObjectURL(blob), download: `${view.report.id}.json` });
  a.click();
  URL.revokeObjectURL(a.href);
};

$("btn-import").onclick = () => {
  $("import-modal").classList.remove("hidden");
  $("import-errors").textContent = "";
};
$("btn-cancel-import").onclick = () => $("import-modal").classList.add("hidden");
$("btn-fill-sample").onclick = async () => {
  try {
    const sample = await (await fetch("/static/sample.json")).json();
    $("import-text").value = JSON.stringify(sample, null, 2);
  } catch (e) {
    toast("示例加载失败");
  }
};
$("btn-do-import").onclick = async () => {
  let body;
  try { body = JSON.parse($("import-text").value); }
  catch (e) { $("import-errors").textContent = "JSON 解析失败：" + e.message; return; }
  const r = await fetch("/api/import", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) {
    $("import-errors").textContent = (data.errors || ["导入失败"]).map((x, i) => `${i + 1}. ${x}`).join("\n");
    return;
  }
  $("import-modal").classList.add("hidden");
  view = { slots: data.slots, segments: data.segments, result: data.result, report: null };
  render();
  toast(`导入成功：${data.slots.length} 个广告位，${data.segments.length} 个片段`);
};

$("btn-report").onclick = async () => {
  const r = await fetch("/api/reports", { method: "POST" });
  if (!r.ok) { toast("报告生成失败"); return; }
  const report = await r.json();
  toast(`报告已保存：${report.id}`);
  await loadReports();
};

// 启动
(async function init() {
  await loadCurrent();
  await loadReports();
})();
