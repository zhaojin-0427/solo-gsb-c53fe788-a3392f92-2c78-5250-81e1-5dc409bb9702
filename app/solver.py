"""核销分配核心（OR-Tools CP-SAT）。

模型
----
对每个广告位 s，在其实匹配素材的片段上建一条“源区间拼接路径”：

* start(s,g): g 为路径首片段 —— src_start=0 且 |air_start-planned_start| <= tolerance
* edge(s,g,h): g 的下一拼片段为 h —— src_end[g]=src_start[h]（源区间首尾相接，
  无重叠无缺口），且 0 <= air_start[h]-air_end[g] <= max_pause（播出同序、
  相邻不重叠且停顿不超过上限）
* end(s,g): g 为末片段 —— src_end[g]=duration
* 流平衡：每个入选项入边/出边各恰有一条，形成 start→end 的单一路径
* 全局：每个片段在所有广告位上至多被选用一次（片段不得复用）

分层目标
~~~~~~~~
1) 最大化核销位数
2) 最小化首片段播出起点相对计划起点的偏差总和
3) 平局：先取已核销位 ID 升序列表（长度固定）字典序最小，再按广告位 ID 升序逐一取
   其片段 ID 序列字典序最小（分层贪心 + 可行性求解；可行性均叠加前两层最优值约束）
"""
from __future__ import annotations

from typing import Any

from ortools.sat.python import cp_model


def _prepare(slots: list[dict], segments: list[dict]) -> dict:
    seg_by_id = {g["seg_id"]: g for g in segments}
    slot_ids = sorted(s["slot_id"] for s in slots)
    slot_by_id = {s["slot_id"]: s for s in slots}
    seg_ids_sorted = sorted(seg_by_id)

    ctx_slots: dict[str, dict] = {}
    for s in slot_ids:
        slot = slot_by_id[s]
        mat = slot["material_id"]
        cand = [g for g in seg_ids_sorted if seg_by_id[g]["material_id"] == mat]

        start_ok = [
            g for g in cand
            if seg_by_id[g]["src_start"] == 0
            and abs(seg_by_id[g]["air_start"] - slot["planned_start"]) <= slot["tolerance"]
        ]
        end_ok = {g for g in cand if seg_by_id[g]["src_end"] == slot["duration"]}

        edges: dict[str, list[str]] = {g: [] for g in cand}
        for g in cand:
            sg = seg_by_id[g]
            for h in cand:
                if h == g:
                    continue
                sh = seg_by_id[h]
                if sh["src_start"] != sg["src_end"]:
                    continue
                pause = sh["air_start"] - sg["air_end"]
                if 0 <= pause <= slot["max_pause"]:
                    edges[g].append(h)
            edges[g].sort()

        # 仅保留位于某条 start→end 路径上的节点与边：
        # 正向（从首片段可达）与反向（可到达末片段）取交集
        reachable: set[str] = set()
        stack = list(start_ok)
        while stack:
            g = stack.pop()
            if g in reachable:
                continue
            reachable.add(g)
            stack.extend(edges[g])

        can_end: set[str] = set(end_ok)
        changed = True
        while changed:
            changed = False
            for g in cand:
                if g not in can_end and any(h in can_end for h in edges[g]):
                    can_end.add(g)
                    changed = True

        node_set = reachable & can_end
        nodes = sorted(node_set)
        start_nodes = sorted(g for g in start_ok if g in node_set)
        end_nodes = sorted(g for g in end_ok if g in node_set)
        node_edges = {g: [h for h in edges[g] if h in node_set] for g in nodes}

        # 单广告位（忽略全局互斥）是否存在拼满路径
        alone_feasible = bool(start_nodes) and bool(end_nodes)

        ctx_slots[s] = {
            "slot": slot,
            "nodes": nodes,
            "starts": sorted(start_nodes),
            "ends": end_nodes,
            "edges": node_edges,
            "alone_feasible": alone_feasible,
            "has_raw_start": bool(start_ok),
        }

    return {
        "slots": slot_ids,
        "slot_by_id": slot_by_id,
        "segments": seg_ids_sorted,
        "seg_by_id": seg_by_id,
        "ctx": ctx_slots,
    }


def _build_template(ctx_data: dict) -> dict:
    """一次性构建无目标、无额外固定约束的基础模型（分层求解时 deepcopy 复用）。"""
    import copy as _copy

    model = cp_model.CpModel()
    f: dict[str, cp_model.IntVar] = {}
    starts: dict[tuple, cp_model.IntVar] = {}
    edges_v: dict[tuple, cp_model.IntVar] = {}
    ends_v: dict[tuple, cp_model.IntVar] = {}
    x: dict[tuple, cp_model.IntVar] = {}

    for s in ctx_data["slots"]:
        info = ctx_data["ctx"][s]
        f[s] = model.NewBoolVar(f"f::{s}")
        for g in info["nodes"]:
            x[(s, g)] = model.NewBoolVar(f"x::{s}::{g}")
        for g in info["starts"]:
            starts[(s, g)] = model.NewBoolVar(f"st::{s}::{g}")
        model.Add(sum(starts[(s, g)] for g in info["starts"]) == f[s])
        for g in info["ends"]:
            ends_v[(s, g)] = model.NewBoolVar(f"en::{s}::{g}")
        model.Add(sum(ends_v[(s, g)] for g in info["ends"]) == f[s])

        def edge_var(a: str, b: str) -> cp_model.IntVar:
            key = (s, a, b)
            if key not in edges_v:
                edges_v[key] = model.NewBoolVar(f"ed::{s}::{a}::{b}")
            return edges_v[key]

        for g in info["nodes"]:
            # 边变量按需创建（入/出引用同一变量）
            incoming: list[cp_model.IntVar] = []
            for a in info["nodes"]:
                if g in info["edges"][a]:
                    incoming.append(edge_var(a, g))
            if (s, g) in starts:
                incoming.append(starts[(s, g)])
            outgoing: list[cp_model.IntVar] = []
            for h in info["edges"][g]:
                outgoing.append(edge_var(g, h))
            if (s, g) in ends_v:
                outgoing.append(ends_v[(s, g)])
            model.Add(sum(incoming) == x[(s, g)])
            model.Add(sum(outgoing) == x[(s, g)])

    # 片段全局互斥：不得复用
    for g in ctx_data["segments"]:
        users = [x[(s, g)] for s in ctx_data["slots"] if (s, g) in x]
        if users:
            model.Add(sum(users) <= 1)

    return {"model": model, "f": f, "starts": starts, "edges": edges_v,
            "ends": ends_v, "x": x, "copy": _copy.deepcopy}


def _var(key, tpl):
    kind = key[0]
    if kind == "f":
        return tpl["f"][key[1]]
    if kind == "st":
        return tpl["starts"][(key[1], key[2])]
    if kind == "ed":
        return tpl["edges"][(key[1], key[2], key[3])]
    return tpl["ends"][(key[1], key[2])]


def _solve(
    tpl: dict,
    ctx_data: dict,
    mode: str,
    fixed: dict[tuple, int],
    target_count: int | None = None,
    target_dev: int | None = None,
) -> dict[str, Any]:
    """mode: 'count' 最大化位数 / 'dev' 最小化偏差和 / 'feas' 仅可行性。

    target_count 固定核销位数；target_dev 固定首播偏差总和（保证后层平局
    判定只在前层最优值上进行）。
    """
    model = tpl["copy"](tpl["model"])
    f, starts, edges_v, ends_v = tpl["f"], tpl["starts"], tpl["edges"], tpl["ends"]
    seg_by_id = ctx_data["seg_by_id"]

    dev_terms = [
        abs(seg_by_id[g]["air_start"] - ctx_data["slot_by_id"][s]["planned_start"]) * v
        for (s, g), v in starts.items()
    ]

    for key, val in fixed.items():
        model.Add(_var(key, tpl) == val)

    if target_count is not None:
        model.Add(sum(f.values()) == target_count)
    if target_dev is not None:
        model.Add(sum(dev_terms) == target_dev)

    if mode == "count":
        model.Maximize(sum(f.values()))
    elif mode == "dev":
        model.Minimize(sum(dev_terms))

    solver = cp_model.CpSolver()
    if mode == "feas":
        # 分层平局判定中的可行性模型：单线程快速判定
        solver.parameters.num_search_workers = 1
        solver.parameters.max_time_in_seconds = 10.0
    else:
        solver.parameters.max_time_in_seconds = 30.0
        solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 42
    status = solver.Solve(model)

    result: dict[str, Any] = {"status": solver.StatusName(status), "ok": status in (
        cp_model.OPTIMAL, cp_model.FEASIBLE)}
    if result["ok"]:
        result["f"] = {s: solver.Value(f[s]) for s in f}
        result["starts"] = {k: solver.Value(v) for k, v in starts.items()}
        result["edges"] = {k: solver.Value(v) for k, v in edges_v.items()}
        result["ends"] = {k: solver.Value(v) for k, v in ends_v.items()}
        result["count"] = sum(result["f"].values())
        if mode in ("dev", "feas"):
            result["deviation"] = sum(
                abs(seg_by_id[g]["air_start"] - ctx_data["slot_by_id"][s]["planned_start"])
                for (s, g), val in result["starts"].items() if val
            )
        if mode == "count":
            result["objective"] = result["count"]
        elif mode == "dev":
            result["objective"] = result["deviation"]
    return result


def allocate(slots: list[dict], segments: list[dict]) -> dict[str, Any]:
    ctx_data = _prepare(slots, segments)
    slot_ids = ctx_data["slots"]

    if not slot_ids:
        return _assemble(ctx_data, set(), {})

    tpl = _build_template(ctx_data)

    def feasible(fixed: dict[tuple, int]) -> bool:
        return _solve(tpl, ctx_data, "feas", fixed, k, total_dev)["ok"]

    # —— 第一层：最大化核销位数 ——
    r1 = _solve(tpl, ctx_data, "count", {}, None)
    if not r1["ok"]:
        raise RuntimeError(f"求解失败：{r1['status']}")
    k = r1["count"]

    if k == 0:
        return _assemble(ctx_data, set(), {})

    fixed: dict[tuple, int] = {}

    # —— 第二层：最小化首播起点偏差总和 ——
    r2 = _solve(tpl, ctx_data, "dev", fixed, k)
    if not r2["ok"]:
        raise RuntimeError(f"偏差优化求解失败：{r2['status']}")
    total_dev = r2["deviation"]

    # —— 第三层：已核销位 ID 升序列表字典序最小 ——
    # 列表长度恒为 k：从最小 ID 起逐位贪心，每次在“此前未选位固定不核销”的
    # 前提下取最小的可入选 ID，直至选满 k 位。
    verified: list[str] = []
    for s in slot_ids:
        if len(verified) == k:
            fixed[("f", s)] = 0
            continue
        trial = {**fixed, ("f", s): 1}
        if feasible(trial):
            fixed = trial
            verified.append(s)
        else:
            fixed[("f", s)] = 0
    verified_set = set(verified)

    # —— 第四层：各广告位（ID 升序）片段 ID 序列字典序最小 ——
    for s in verified:
        info = ctx_data["ctx"][s]
        end_set = set(info["ends"])
        # 首片段：取可行的最小片段 ID
        chosen_first = None
        for g in info["starts"]:
            trial = {**fixed, ("st", s, g): 1}
            if feasible(trial):
                fixed = trial
                chosen_first = g
                break
        cur = chosen_first
        while cur is not None:
            # 能否在此收尾：能收尾则短序列字典序更小
            if cur in end_set:
                trial = {**fixed, ("en", s, cur): 1}
                if feasible(trial):
                    fixed = trial
                    break
            nxt = None
            for h in info["edges"][cur]:
                trial = {**fixed, ("ed", s, cur, h): 1}
                if feasible(trial):
                    fixed = trial
                    nxt = h
                    break
            cur = nxt

    last = _solve(tpl, ctx_data, "feas", fixed, k, total_dev)
    if not last["ok"]:
        raise RuntimeError(f"终局可行性求解失败：{last['status']}")
    chosen_firsts = {s: next(g for (ss, g), v in last["starts"].items() if ss == s and v)
                     for s in verified}
    chosen_ends = {ss: g for (ss, g), v in last["ends"].items() if v}
    chosen_next: dict[tuple[str, str], str] = {
        (ss, a): h for (ss, a, h), v in last["edges"].items() if v
    }
    chosen: dict[str, list[str]] = {}
    for s in verified:
        seq = [chosen_firsts[s]]
        while seq[-1] != chosen_ends[s]:
            seq.append(chosen_next[(s, seq[-1])])
        chosen[s] = seq

    return _assemble(ctx_data, verified_set, chosen, total_dev)


def _assemble(
    ctx_data: dict,
    verified: set[str],
    chosen: dict[str, list[str]],
    total_dev: int | None = None,
) -> dict[str, Any]:
    seg_by_id = ctx_data["seg_by_id"]
    slot_by_id = ctx_data["slot_by_id"]
    used_seg_ids = sorted({g for seq in chosen.values() for g in seq})
    if total_dev is None:
        total_dev = sum(
            abs(seg_by_id[seq[0]]["air_start"] - slot_by_id[s]["planned_start"])
            for s, seq in chosen.items()
        )

    verified_out: list[dict] = []
    for s in sorted(verified):
        slot = slot_by_id[s]
        seq = chosen[s]
        segs = [seg_by_id[g] for g in seq]
        first = segs[0]
        pauses = []
        for a, b in zip(segs, segs[1:]):
            pauses.append({
                "from": a["seg_id"],
                "to": b["seg_id"],
                "air_gap_ms": b["air_start"] - a["air_end"],
                "source_concat": [a["src_end"], b["src_start"]],
            })
        dev = abs(first["air_start"] - slot["planned_start"])
        verified_out.append({
            "slot_id": s,
            "material_id": slot["material_id"],
            "planned_start": slot["planned_start"],
            "duration": slot["duration"],
            "tolerance": slot["tolerance"],
            "max_pause": slot["max_pause"],
            "segment_ids": seq,
            "first_air_start": first["air_start"],
            "start_deviation_ms": dev,
            "evidence": {
                "material_consistent": all(seg_by_id[g]["material_id"] == slot["material_id"] for g in seq),
                "source_intervals": [[g["src_start"], g["src_end"]] for g in segs],
                "source_covers": [0, slot["duration"]],
                "source_no_gap_no_overlap": all(
                    a["src_end"] == b["src_start"] for a, b in zip(segs, segs[1:])
                ) and segs[0]["src_start"] == 0 and segs[-1]["src_end"] == slot["duration"],
                "air_intervals": [[g["air_start"], g["air_end"]] for g in segs],
                "air_order_consistent": all(
                    b["air_start"] >= a["air_end"] for a, b in zip(segs, segs[1:])
                ),
                "pauses": pauses,
                "pauses_within_limit": all(p["air_gap_ms"] <= slot["max_pause"] for p in pauses),
                "first_start_within_tolerance": dev <= slot["tolerance"],
            },
        })

    # 未核销位原因（忽略全局互斥后的独立可达性诊断）
    unverified_out: list[dict] = []
    referenced_materials = {s["material_id"] for s in ctx_data["slot_by_id"].values()}
    for s in ctx_data["slots"]:
        if s in verified:
            continue
        slot = slot_by_id[s]
        info = ctx_data["ctx"][s]
        if not info["has_raw_start"]:
            reason = "无满足首片段条件的素材（需源起点为 0 且播出起点在计划起点±容差内）"
        elif not info["alone_feasible"]:
            reason = "同素材片段无法按源顺序无缺口拼满 [0, 时长)：源拼接缺口/长度不符，或相邻播出停顿超出上限"
        else:
            reason = "单广告位存在可行拼满序列，但全局分配受片段不得复用约束及分层目标限制未入选"
        unverified_out.append({
            "slot_id": s,
            "material_id": slot["material_id"],
            "planned_start": slot["planned_start"],
            "duration": slot["duration"],
            "tolerance": slot["tolerance"],
            "max_pause": slot["max_pause"],
            "reason": reason,
        })

    idle_out: list[dict] = []
    for g in ctx_data["segments"]:
        if g in used_seg_ids:
            continue
        seg = seg_by_id[g]
        reason = "素材无对应广告位" if seg["material_id"] not in referenced_materials else "未被核销方案选用"
        idle_out.append({**seg, "reason": reason})

    return {
        "verified_count": len(verified_out),
        "total_start_deviation_ms": total_dev,
        "verified_slots": verified_out,
        "unverified_slots": unverified_out,
        "idle_segments": idle_out,
        "used_segment_ids": used_seg_ids,
        "segment_reuse_ok": len(used_seg_ids) == len(set(used_seg_ids)),
        "objectives": {
            "primary": "最大化核销位数",
            "secondary": "最小化首片段播出起点偏差总和（整数毫秒绝对值）",
            "tie_break": "同分依次取：已核销位 ID 升序列表字典序最小；各广告位（按位 ID 升序）片段 ID 序列字典序最小",
        },
    }
