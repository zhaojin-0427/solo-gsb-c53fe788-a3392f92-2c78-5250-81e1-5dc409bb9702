/* 广告播出核销前端 —— 原生 JavaScript，无任何第三方依赖。 */
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  view: "latest", // "latest" | "history"
  current: null, // { report_id, created_at, input, result }
};

/* ---------------- 工具 ---------------- */

function fmt(v) {
  return Number(v).toLocaleString("en-US");
}

function intervalText(a, b) {
  return `[${fmt(a)}, ${fmt(b)}) · ${fmt(b - a)} ms`;
}

function niceStep(range, target = 8) {
  const raw = range / target;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / pow;
  let m;
  if (n < 1.5) m = 1;
  else if (n < 3) m = 2;
  else if (n < 7) m = 5;
  else m = 10;
  return m * pow;
}

function pct(t, tMin, range) {
  return ((t - tMin) / range) * 100;
}

function buildScale(view) {
  const { input } = view;
  let lo = Infinity, hi = -Infinity;
  const pushRange = (a, b) => { lo = Math.min(lo, a); hi = Math.max(hi, b); };
  input.slots.forEach((s) => {
    pushRange(s.planned_start - s.tolerance, s.planned_start + s.duration);
  });
  input.fragments.forEach((f) => pushRange(f.on_air_start, f.on_air_end));
  if (!isFinite(lo)) { lo = 0; hi = 1; }
  if (hi <= lo) hi = lo + 1;
  return { tMin: lo, tMax: hi, range: hi - lo };
}

/* ---------------- 时间轴渲染 ---------------- */

function renderAxis(axisEl, scale) {
  const { tMin, range, tMax } = scale;
  const step = niceStep(range);
  axisEl.innerHTML = "";
  let first = Math.ceil(tMin / step) * step;
  for (let t = first; t <= tMax; t += step) {
    const tick = document.createElement("div");
    tick.className = "tick";
    tick.style.left = `${pct(t, tMin, range)}%`;
    tick.textContent = fmt(t);
    axisEl.appendChild(tick);
  }
}

function attachTooltip(el, html) {
  el.addEventListener("mouseenter", (e) => {
    const tip = $("tooltip");
    tip.innerHTML = html;
    tip.classList.remove("hidden");
    moveTip(e);
  });
  el.addEventListener("mousemove", moveTip);
  el.addEventListener("mouseleave", () => $("tooltip").classList.add("hidden"));
}

function moveTip(e) {
  const tip = $("tooltip");
  const pad = 14;
  let x = e.clientX + pad;
  let y = e.clientY + pad;
  const rect = tip.getBoundingClientRect();
  if (x + rect.width > window.innerWidth - 8) x = e.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight - 8) y = e.clientY - rect.height - pad;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}

function makeBar(laneEl, t0, t1, scale, cls, label, tipHtml) {
  const bar = document.createElement("div");
  bar.className = `bar ${cls}`;
  bar.style.left = `${pct(t0, scale.tMin, scale.range)}%`;
  bar.style.width = `${Math.max(pct(t1 - t0, 0, scale.range), 0.25)}%`;
  bar.textContent = label;
  laneEl.appendChild(bar);
  if (tipHtml) attachTooltip(bar, tipHtml);
  return bar;
}

function renderPlanTimeline(view, scale) {
  const root = $("timeline-plan");
  root.innerHTML = "";
  const verifiedById = {};
  view.result.verified.forEach((v) => { verifiedById[v.slot_id] = v; });

  view.input.slots.forEach((s) => {
    const lane = document.createElement("div");
    lane.className = "lane";
    const label = document.createElement("div");
    label.className = "lane-label";
    label.textContent = s.id;
    label.title = `${s.id} / ${s.material_id}`;
    lane.appendChild(label);

    // 容差窗（覆盖首片段可能的起点范围）
    const tol = document.createElement("div");
    tol.className = "tol-window";
    const tolA = s.planned_start - s.tolerance;
    const tolB = s.planned_start + s.tolerance;
    tol.style.left = `${pct(tolA, scale.tMin, scale.range)}%`;
    tol.style.width = `${Math.max(pct(tolB - tolA, 0, scale.range), 0.2)}%`;
    lane.appendChild(tol);
    attachTooltip(
      tol,
      `广告位 <b>${s.id}</b><br>计划起点 ${fmt(s.planned_start)} ± ${fmt(s.tolerance)}<br>` +
      `时长 ${fmt(s.duration)} · 最大停顿 ${fmt(s.max_gap)}`
    );

    const v = verifiedById[s.id];
    const cls = v ? "plan-verified" : "plan-unverified";
    const devTxt = v
      ? ` <span class="bar-dev">Δ${v.deviation === 0 ? "=0" : (v.deviation > 0 ? "+" : "") + fmt(v.deviation)}</span>`
      : "";
    const bar = makeBar(
      lane,
      s.planned_start,
      s.planned_start + s.duration,
      scale,
      cls,
      `${s.id} · ${s.material_id}${devTxt}`,
      `广告位 <b>${s.id}</b>（素材 ${s.material_id}）<br>` +
      `计划区间 ${intervalText(s.planned_start, s.planned_start + s.duration)}<br>` +
      `容差 ±${fmt(s.tolerance)} · 最大停顿 ${fmt(s.max_gap)}<br>` +
      (v
        ? `已核销 · 首片段起点 ${fmt(v.first_start)} · 偏差 ${fmt(v.deviation)}`
        : "未核销")
    );
    root.appendChild(lane);
  });
}

function packLanes(frags) {
  // 简单贪心装箱：按开始时间排序，依次放入最早空出的泳道
  const order = frags
    .map((f, idx) => ({ f, idx }))
    .sort((a, b) => a.f.on_air_start - b.f.on_air_start ||
                    a.f.on_air_end - b.f.on_air_end);
  const laneEnds = [];
  const laneOf = new Array(frags.length);
  for (const { f, idx } of order) {
    let placed = -1;
    for (let k = 0; k < laneEnds.length; k++) {
      if (laneEnds[k] <= f.on_air_start) { placed = k; break; }
    }
    if (placed === -1) { placed = laneEnds.length; laneEnds.push(0); }
    laneEnds[placed] = f.on_air_end;
    laneOf[idx] = placed;
  }
  return { laneOf, laneCount: laneEnds.length };
}

function renderAirTimeline(view, scale) {
  const root = $("timeline-air");
  root.innerHTML = "";
  const frags = view.input.fragments;

  // 片段 -> 分配给的广告位 / 顺序
  const fragOwner = {};
  view.result.verified.forEach((v) => {
    v.fragment_ids.forEach((fid, order) => {
      fragOwner[fid] = { slotId: v.slot_id, order, dev: v.deviation };
    });
  });

  const { laneOf, laneCount } = packLanes(frags);
  const lanes = [];
  for (let k = 0; k < Math.max(laneCount, 1); k++) {
    const lane = document.createElement("div");
    lane.className = "lane";
    const label = document.createElement("div");
    label.className = "lane-label";
    label.textContent = `L${k + 1}`;
    lane.appendChild(label);
    root.appendChild(lane);
    lanes.push(lane);
  }

  frags.forEach((f, idx) => {
    const owner = fragOwner[f.id];
    const cls = owner ? "frag-used" : "frag-idle";
    const label = owner ? `${f.id}→${owner.slotId}` : f.id;
    makeBar(
      lanes[laneOf[idx]],
      f.on_air_start,
      f.on_air_end,
      scale,
      cls,
      label,
      `片段 <b>${f.id}</b>（素材 ${f.material_id}）<br>` +
      `播出 ${intervalText(f.on_air_start, f.on_air_end)}<br>` +
      `素材源 ${intervalText(f.source_start, f.source_end)}<br>` +
      (owner
        ? `已分配给广告位 <b>${owner.slotId}</b>（第 ${owner.order + 1} 段）`
        : "<b>闲置片段</b>")
    );
  });

  // 相邻片段之间的停顿标记（在已核销序列上）
  view.result.verified.forEach((v) => {
    v.fragments.forEach((p) => {
      if (p.pause_before === null || p.pause_before < 0) return;
      const f = view.input.fragments.find((x) => x.id === p.fragment_id);
      const idx = frags.indexOf(f);
      const laneEl = lanes[laneOf[idx]];
      const mark = document.createElement("div");
      mark.className = "pause-mark";
      mark.style.left = `${pct(f.on_air_start, scale.tMin, scale.range)}%`;
      mark.title = `${v.slot_id}：停顿 ${p.pause_before} ms`;
      attachTooltip(
        mark,
        `广告位 <b>${v.slot_id}</b><br>片段 ${p.fragment_id} 前停顿 ${fmt(p.pause_before)} ms`
      );
      laneEl.appendChild(mark);
    });
  });
}

/* ---------------- 证据 / 剩余项 ---------------- */

function renderDetails(view) {
  const r = view.result;

  // 已核销
  const vl = $("verified-list");
  vl.innerHTML = "";
  if (!r.verified.length) {
    vl.innerHTML = '<p class="muted">本次无核销广告位</p>';
  }
  r.verified.forEach((v) => {
    const card = document.createElement("div");
    card.className = "card ok";
    const devCls = v.deviation === 0 ? "dev-pill zero" : "dev-pill";
    card.innerHTML =
      `<div class="card-title">${v.slot_id} · ${v.material_id}` +
      `<span class="${devCls}">首播偏差 ${v.deviation > 0 ? "+" : ""}${fmt(v.deviation)} ms</span></div>` +
      `<div class="card-meta">计划起点 ${fmt(v.planned_start)} · 时长 ${fmt(v.duration)} · ` +
      `容差 ±${fmt(v.tolerance)} · 最大停顿 ${fmt(v.max_gap)} · 实际首播 ${fmt(v.first_start)} · ` +
      `${v.fragment_ids.length} 个片段</div>`;
    const chain = document.createElement("div");
    chain.className = "chain";
    v.fragments.forEach((p, i) => {
      if (i > 0) {
        const arr = document.createElement("span");
        arr.className = "arr";
        arr.innerHTML = `──<b>停顿 ${fmt(p.pause_before)}</b>→`;
        chain.appendChild(arr);
      }
      const seg = document.createElement("span");
      seg.className = "seg";
      seg.innerHTML =
        `${p.fragment_id} <span class="src">源 ${fmt(p.source_start)}–${fmt(p.source_end)}` +
        ` / 播 ${fmt(p.on_air_start)}–${fmt(p.on_air_end)}</span>`;
      seg.title =
        `片段 ${p.fragment_id}\n素材源 ${intervalText(p.source_start, p.source_end)}\n` +
        `播出 ${intervalText(p.on_air_start, p.on_air_end)}` +
        (p.pause_before !== null ? `\n前段停顿 ${p.pause_before} ms` : "");
      chain.appendChild(seg);
    });
    card.appendChild(chain);
    vl.appendChild(card);
  });

  // 未核销
  const ul = $("unverified-list");
  ul.innerHTML = r.unverified.length ? "" : '<p class="muted">全部广告位均已核销 🎉</p>';
  r.unverified.forEach((s) => {
    const card = document.createElement("div");
    card.className = "card bad";
    card.innerHTML =
      `<div class="card-title">${s.id} · ${s.material_id}</div>` +
      `<div class="card-meta">计划起点 ${fmt(s.planned_start)} · 时长 ${fmt(s.duration)} · ` +
      `容差 ±${fmt(s.tolerance)} · 最大停顿 ${fmt(s.max_gap)}</div>` +
      `<div>未核销原因：${s.reason}</div>`;
    ul.appendChild(card);
  });

  // 闲置片段
  const il = $("idle-list");
  il.innerHTML = r.idle_fragments.length ? "" : '<p class="muted">实播片段已全部分配</p>';
  r.idle_fragments.forEach((f) => {
    const card = document.createElement("div");
    card.className = "card idle";
    card.innerHTML =
      `<div class="card-title">${f.id} · ${f.material_id}</div>` +
      `<div class="card-meta">播出 ${intervalText(f.on_air_start, f.on_air_end)} · ` +
      `素材源 ${intervalText(f.source_start, f.source_end)}</div>`;
    il.appendChild(card);
  });

  // 概要
  const sm = $("summary");
  sm.classList.remove("hidden");
  let note = "";
  if (!r.tie_break_complete) {
    note = `<div class="solver-note">⚠ 最优解数量过多（枚举超过上限），字典序裁决为尽力而为；` +
      `前两级目标（核销位数、偏差和）仍为最优。</div>`;
  }
  sm.innerHTML =
    `<b>${r.verified_count}</b> / ${view.input.slots.length} 个广告位核销 · ` +
    `首播起点绝对偏差总和 <b>${fmt(r.total_deviation)}</b> ms · ` +
    `闲置片段 ${r.idle_fragments.length} · 求解耗时 ${r.solve_time_ms} ms` +
    (r.solutions_seen ? ` · 枚举最优解 ${r.solutions_seen} 个` : "") + note;
}

/* ---------------- 总渲染 ---------------- */

function renderAll() {
  const view = state.current;
  if (!view) {
    $("summary").classList.add("hidden");
    return;
  }
  const scale = buildScale(view);
  renderAxis($("axis-plan"), scale);
  renderAxis($("axis-air"), scale);
  renderPlanTimeline(view, scale);
  renderAirTimeline(view, scale);
  renderDetails(view);

  const banner = $("history-banner");
  if (state.view === "history") {
    banner.classList.remove("hidden");
    $("history-id").textContent = view.report_id;
    $("history-time").textContent = `生成于 ${view.created_at}`;
  } else {
    banner.classList.add("hidden");
  }
}

/* ---------------- 报告列表 / API ---------------- */

async function loadReports(activeId) {
  const res = await fetch("/api/reports");
  const data = await res.json();
  const root = $("report-list");
  root.innerHTML = "";
  if (!data.reports.length) {
    root.innerHTML = '<p class="muted">尚无报告</p>';
    return;
  }
  data.reports.forEach((r) => {
    const row = document.createElement("div");
    row.className = "report-row";
    if (r.id === activeId) row.classList.add("active");
    row.innerHTML =
      `<div class="rr-top"><code>${r.id.slice(0, 12)}…</code>` +
      `<span class="${r.is_latest ? "badge-latest" : "badge-nonlatest"}">` +
      (r.is_latest ? "最新" : "历史") + `</span></div>` +
      `<div class="rr-meta">${r.created_at.replace("T", " ").replace("+00:00", " UTC")}` +
      ` · ${r.channel || "（未命名频道）"}<br>` +
      `核销 ${r.verified_count}/${r.slot_count} · 偏差和 ${fmt(r.total_deviation)} · ` +
      `片段 ${r.fragment_count}</div>`;
    row.addEventListener("click", () => selectReport(r.id));
    root.appendChild(row);
  });
}

async function selectReport(id) {
  const res = await fetch(`/api/reports/${id}`);
  if (!res.ok) return;
  const report = await res.json();
  state.current = {
    report_id: report.id,
    created_at: report.created_at,
    input: report.input,
    result: report.result,
  };
  state.view = report.is_latest ? "latest" : "history";
  $("json-input").value = JSON.stringify(report.input, null, 2);
  renderAll();
  loadReports(id);
}

async function runVerify() {
  $("errors").classList.add("hidden");
  let payload;
  try {
    payload = JSON.parse($("json-input").value);
  } catch (e) {
    showErrors([`JSON 解析失败：${e.message}`]);
    return;
  }
  const res = await fetch("/api/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.status === 422) {
    const data = await res.json();
    showErrors(data.detail.errors || [JSON.stringify(data.detail)]);
    return;
  }
  if (!res.ok) {
    showErrors([`服务错误：HTTP ${res.status}`]);
    return;
  }
  const data = await res.json();
  state.current = {
    report_id: data.report_id,
    created_at: data.created_at,
    input: data.input,
    result: data.result,
  };
  state.view = "latest";
  $("json-input").value = JSON.stringify(data.input, null, 2);
  renderAll();
  loadReports(data.report_id);
}

function showErrors(errors) {
  const el = $("errors");
  el.textContent = errors.map((e, i) => `${i + 1}. ${e}`).join("\n");
  el.classList.remove("hidden");
}

/* ---------------- 初始化 ---------------- */

async function init() {
  $("btn-verify").addEventListener("click", runVerify);
  $("btn-sample").addEventListener("click", async () => {
    const res = await fetch("/api/sample");
    const data = await res.json();
    $("json-input").value = JSON.stringify(data, null, 2);
  });
  $("btn-clear-history").addEventListener("click", async () => {
    await loadReports(null);
    const res = await fetch("/api/reports");
    const data = await res.json();
    if (data.reports.length) {
      await selectReport(data.reports[0].id); // 列表按时间倒序，首条即最新
    } else {
      state.current = null;
      state.view = "latest";
      renderAll();
    }
  });

  const reports = await fetch("/api/reports").then((r) => r.json());
  if (reports.reports.length) {
    await selectReport(reports.reports[0].id);
  } else {
    const res = await fetch("/api/sample");
    $("json-input").value = JSON.stringify(await res.json(), null, 2);
    loadReports(null);
  }
}

window.addEventListener("resize", () => { if (state.current) renderAll(); });
init();
