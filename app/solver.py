"""广告位核销的 CP-SAT 全局分配模型。

业务规则（半开区间，整数毫秒）：

一个广告位 i 被核销（z_i=1），当且仅当存在一个有序片段序列 f_0..f_{q-1}：

1. 素材一致：所有片段 material_id 与广告位相同；
2. 素材源拼满且无重叠/缺口：源区间按源顺序恰好拼成 [0, duration)
   （源区间左端点必须覆盖到 0）；
3. 播出顺序与源顺序一致：序列按源起点升序，播出起点同样严格非递减；
4. 相邻播出片段不重叠且停顿不超过 max_gap：
   0 <= on_air_start(f_{k+1}) - on_air_end(f_k) <= max_gap；
5. 首片段播出起点在 [planned_start - tolerance, planned_start + tolerance]；
6. 片段全局唯一使用：同一实播片段不能分配给多个广告位，也不能重复使用。

目标（字典序）：
  (a) 最大化核销广告位数量；
  (b) 最小化全部核销广告位“首片段播出起点 - planned_start”绝对偏差之和；
  (c) 仍同分时，取（已核销位 ID 列表，各广告位片段 ID 序列）字典序最小者。

建模要点（每广告位 i，候选片段集 C_i）：
  y_ij            候选 j 是否被该广告位使用（片段全局 Σ y ≤ 1）
  可选区间 [srcStart_j, srcStart_j+len_j) presence=y_ij，AddNoOverlap 保证源无重叠
  head            存在一个源起点为 0 的选中片段
  succ_{i,a,b}    a,b 均选中且 srcStart_b = srcEnd_a（源紧接）
  核销时：选中片段总长度 == duration、必有 head；每个非头选中片段恰有一个源前驱
          ⇒ 从 0 起、无缺口、无重叠地拼满 [0, duration)
  播出停顿约束挂在 succ 对上；首片段偏差取源起点为 0 的选中片段。

(a)(b) 用加权目标一次求解；(c) 在固定 (a)(b) 最优值后枚举全部最优解，
由 Python 侧按字典序比较选出唯一方案。
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

# 枚举最优解的安全上限（典型数据规模远小于此）；超过则字典序保证为尽力而为
SOLUTION_CAP = 200_000
PHASE1_TIME_LIMIT = 15.0
PHASE2_TIME_LIMIT = 30.0


@dataclass
class _SlotVars:
    slot: dict
    cand_indices: list[int]  # 全局片段下标
    y: list[cp_model.IntVar]
    z: cp_model.IntVar
    first_offset: cp_model.IntVar | None
    dev: cp_model.IntVar


class _Model:
    def __init__(self, slots: list[dict], fragments: list[dict], with_objective: bool):
        self.slots = slots
        self.fragments = fragments
        self.model = cp_model.CpModel()
        self.slot_vars: list[_SlotVars] = []
        self.K = self.model.NewConstant(0)
        self.total_dev = self.model.NewConstant(0)
        self._build(with_objective)

    def _build(self, with_objective: bool) -> None:
        m = self.model
        slots, fragments = self.slots, self.fragments
        nf = len(fragments)

        # 片段长度（播出与源长度相等，已在输入校验中保证）
        length = [f["on_air_end"] - f["on_air_start"] for f in fragments]
        max_end = max((f["on_air_end"] for f in fragments), default=0)

        # 候选：素材一致、源区间可放入 [0, duration)
        candidates: list[list[int]] = []
        for s in slots:
            cands: list[int] = []
            for j, f in enumerate(fragments):
                if f["material_id"] != s["material_id"]:
                    continue
                if f["source_start"] < 0:
                    continue
                if f["source_start"] + length[j] > s["duration"]:
                    continue
                cands.append(j)
            candidates.append(cands)

        # 全局复用：每个片段最多被一个广告位使用
        frag_use: dict[int, list[cp_model.IntVar]] = defaultdict(list)

        z_list: list[cp_model.IntVar] = []
        dev_list: list[cp_model.IntVar] = []

        for i, s in enumerate(slots):
            cands = candidates[i]
            duration = s["duration"]
            t0 = s["tolerance"]

            if not cands:
                sv = _SlotVars(
                    slot=s, cand_indices=[], y=[],
                    z=m.NewConstant(0), first_offset=None,
                    dev=m.NewConstant(0),
                )
                self.slot_vars.append(sv)
                z_list.append(sv.z)
                dev_list.append(sv.dev)
                continue

            z = m.NewBoolVar(f"z_{i}")

            y = [m.NewBoolVar(f"y_{i}_{j}") for j in cands]
            for ci, j in enumerate(cands):
                frag_use[j].append(y[ci])
                # 未核销（z=0）时该广告位不得占用任何片段
                m.Add(y[ci] == 0).OnlyEnforceIf(z.Not())

            # —— 素材源无重叠：按固定源起点建立可选区间 ——
            ivs = [
                m.NewOptionalIntervalVar(
                    fragments[j]["source_start"], length[j],
                    fragments[j]["source_start"] + length[j],
                    y[ci], f"iv_{i}_{j}",
                )
                for ci, j in enumerate(cands)
            ]
            m.AddNoOverlap(ivs)

            # 源起点 -> 候选下标（同一广告位内同素材，源区间相同的多个片段互为替代）
            by_start: dict[int, list[int]] = defaultdict(list)
            for ci, j in enumerate(cands):
                by_start[fragments[j]["source_start"]].append(ci)

            # 头片段（源起点为 0）
            head_cis = by_start.get(0, [])

            # succ[(a,b)]：a 与 b 源区间首尾相接（b.srcStart == a.srcEnd）
            succ: dict[tuple[int, int], cp_model.IntVar] = {}
            for ca, ja in enumerate(cands):
                end_a = fragments[ja]["source_start"] + length[ja]
                for cb in by_start.get(end_a, []):
                    bvar = m.NewBoolVar(f"succ_{i}_{ca}_{cb}")
                    succ[(ca, cb)] = bvar
                    # succ => a、b 均选中
                    m.Add(y[ca] == 1).OnlyEnforceIf(bvar)
                    m.Add(y[cb] == 1).OnlyEnforceIf(bvar)
                    # a、b 均选中 => succ（源坐标下它们必然相邻；
                    # 若中间还夹着别的选中片段，NoOverlap 会直接判冲突）
                    m.AddBoolOr([y[ca].Not(), y[cb].Not(), bvar])

            # z 的含义：选中片段总长度恰好 == duration（配合源无重叠/有头/前驱链）
            selected_len = m.NewIntVar(0, duration, f"selen_{i}")
            m.Add(selected_len == sum(length[j] * y[ci]
                                      for ci, j in enumerate(cands)))
            # z == (selected_len == duration)
            m.Add(selected_len == duration).OnlyEnforceIf(z)
            m.Add(selected_len <= duration - 1).OnlyEnforceIf(z.Not())

            # 核销时必须有头片段（源从 0 开始）
            if head_cis:
                m.Add(sum(y[ci] for ci in head_cis) >= 1).OnlyEnforceIf(z)
            else:
                m.Add(z == 0)

            # 核销时，每个被选中的非头片段必须恰好有一个源前驱
            pred_vars: dict[int, list[cp_model.IntVar]] = defaultdict(list)
            for (a, b), bvar in succ.items():
                pred_vars[b].append(bvar)
            for ci, j in enumerate(cands):
                if fragments[j]["source_start"] == 0:
                    continue
                preds = pred_vars.get(ci, [])
                if preds:
                    has_pred = m.NewBoolVar(f"haspred_{i}_{ci}")
                    m.Add(has_pred == sum(preds))
                    # z & y[ci] => has_pred（线性化：z + y <= has_pred + 1）
                    m.Add(z + y[ci] - has_pred <= 1)
                else:
                    # 无源前缀候选，核销时该片段不可被选中
                    m.Add(z + y[ci] <= 1)

            # —— 首片段（源起点 0）播出起点偏差 ——
            first_offset = m.NewIntVar(-t0, t0, f"roff_{i}")
            head_sum = sum(y[ci] for ci in head_cis)  # 核销时恰为 1
            m.Add(
                first_offset
                == sum(
                    (fragments[cands[ci]]["on_air_start"] - s["planned_start"])
                    * y[ci] for ci in head_cis
                )
            )
            m.Add(first_offset >= -t0).OnlyEnforceIf(z)
            m.Add(first_offset <= t0).OnlyEnforceIf(z)

            # —— 播出侧：源相邻片段必须播出顺序一致、不重叠、停顿 <= max_gap ——
            for (ca, cb), bvar in succ.items():
                ja, jb = cands[ca], cands[cb]
                gap = (
                    fragments[jb]["on_air_start"] - fragments[ja]["on_air_end"]
                )
                # bvar=1 ⇒ 0 <= gap <= max_gap。常量 gap，违反则禁止 bvar=1。
                if gap < 0 or gap > s["max_gap"]:
                    m.Add(bvar == 0)

            dev = m.NewIntVar(0, t0, f"dev_{i}")
            m.Add(dev >= first_offset).OnlyEnforceIf(z)
            m.Add(dev >= -first_offset).OnlyEnforceIf(z)
            m.Add(dev == 0).OnlyEnforceIf(z.Not())

            sv = _SlotVars(
                slot=s, cand_indices=cands, y=y, z=z,
                first_offset=first_offset, dev=dev,
            )
            self.slot_vars.append(sv)
            z_list.append(z)
            dev_list.append(dev)

        for _j, ys in frag_use.items():
            m.Add(sum(ys) <= 1)

        self.K = sum(z_list)
        self.total_dev = sum(dev_list)

        if with_objective:
            # BIG 严格大于任何可能的偏差总和（每个核销位偏差 <= tolerance），
            # 保证“位数”优先级最高
            big = sum(s["tolerance"] for s in slots) + 1
            self.big = big
            m.Maximize(self.K * big - self.total_dev)
        else:
            self.big = None


class _OptimumTracker(cp_model.CpSolverSolutionCallback):
    """第一阶段：记录最优 K 与偏差和。"""

    def __init__(self, model: _Model):
        super().__init__()
        self.model = model
        self.best_obj = None
        self.best_K = 0
        self.best_dev = 0

    def on_solution_callback(self) -> None:
        obj = self.ObjectiveValue()
        k = self.Value(self.model.K)
        dev = self.Value(self.model.total_dev)
        if self.best_obj is None or obj > self.best_obj:
            self.best_obj = obj
            self.best_K = k
            self.best_dev = dev


class _LexCollector(cp_model.CpSolverSolutionCallback):
    """第二阶段：枚举 (K, dev) 最优的所有解，保留字典序最小方案。"""

    def __init__(self, model: _Model):
        super().__init__()
        self.model = model
        self.count = 0
        self.truncated = False
        self.best_key = None
        self.best_assignment: dict[str, list[str]] = {}

    def on_solution_callback(self) -> None:
        self.count += 1
        if self.count > SOLUTION_CAP:
            self.truncated = True
            self.StopSearch()
            return

        fragments = self.model.fragments
        z_bits = []
        sequences = []
        assignment: dict[str, list[str]] = {}
        for sv in self.model.slot_vars:
            zv = self.Value(sv.z)
            z_bits.append(zv)
            chosen = [
                fragments[sv.cand_indices[ci]]["id"]
                for ci, yv in enumerate(sv.y)
                if self.Value(yv)
            ] if sv.y else []
            # 序列按素材源顺序排列
            chosen.sort(key=lambda fid: next(
                f["source_start"] for f in fragments if f["id"] == fid))
            seq = tuple(chosen)
            sequences.append(seq)
            if zv:
                assignment[sv.slot["id"]] = list(seq)

        key = (tuple(z_bits), tuple(sequences))
        if self.best_key is None or key < self.best_key:
            self.best_key = key
            self.best_assignment = assignment


def _verify_assignment(dataset: dict, assignment: dict[str, list[str]]) -> None:
    """按业务规则独立复核求解结果，防止建模缺陷造成误报（仅断言，不做业务）。"""
    slots = {s["id"]: s for s in dataset["slots"]}
    frags = {f["id"]: f for f in dataset["fragments"]}
    used: dict[str, str] = {}
    for sid, seq in assignment.items():
        s = slots[sid]
        assert len(seq) > 0
        assert len(set(seq)) == len(seq), f"{sid}: 片段重复"
        prev_src_end = 0
        prev_air_end = None
        first_start = None
        for k, fid in enumerate(seq):
            assert fid not in used, f"片段 {fid} 被复用"
            used[fid] = sid
            f = frags[fid]
            L = f["on_air_end"] - f["on_air_start"]
            assert L == f["source_end"] - f["source_start"] and L > 0
            assert f["material_id"] == s["material_id"]
            # 源紧密拼满
            assert f["source_start"] == prev_src_end, (
                f"{sid}: 源缺口/重叠 @ {fid}")
            prev_src_end = f["source_end"]
            if k == 0:
                first_start = f["on_air_start"]
                assert abs(first_start - s["planned_start"]) <= s["tolerance"]
                assert f["source_start"] == 0
            else:
                pause = f["on_air_start"] - prev_air_end
                assert 0 <= pause <= s["max_gap"], (
                    f"{sid}: 停顿非法 {pause}")
            prev_air_end = f["on_air_end"]
        assert prev_src_end == s["duration"], f"{sid}: 未拼满 duration"


def solve(dataset: dict) -> dict:
    """对校验后的数据集求解，返回核销结果与分配证据。"""
    slots = dataset["slots"]
    fragments = dataset["fragments"]
    started = time.perf_counter()

    # ---- 第一阶段：最大化位数、最小化偏差和 ----
    phase1 = _Model(slots, fragments, with_objective=True)
    solver1 = cp_model.CpSolver()
    solver1.parameters.max_time_in_seconds = PHASE1_TIME_LIMIT
    solver1.parameters.num_search_workers = 8
    tracker = _OptimumTracker(phase1)
    status1 = solver1.Solve(phase1.model, tracker)

    if status1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE) or tracker.best_obj is None:
        # 模型天然可行（全部不核销），走到这里属于求解器异常
        k_opt, dev_opt = 0, 0
        status_name = solver1.StatusName(status1)
    else:
        k_opt = tracker.best_K
        dev_opt = tracker.best_dev
        status_name = solver1.StatusName(status1)

    # ---- 第二阶段：固定 (K, dev) 枚举全部最优解做字典序裁决 ----
    phase2 = _Model(slots, fragments, with_objective=False)
    phase2.model.Add(phase2.K == k_opt)
    phase2.model.Add(phase2.total_dev == dev_opt)
    solver2 = cp_model.CpSolver()
    solver2.parameters.enumerate_all_solutions = True
    solver2.parameters.num_search_workers = 1
    solver2.parameters.max_time_in_seconds = PHASE2_TIME_LIMIT
    collector = _LexCollector(phase2)
    status2 = solver2.Solve(phase2.model, collector)
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    assignment = collector.best_assignment or {}
    _verify_assignment(dataset, assignment)
    return _build_result(
        dataset,
        assignment,
        k_opt,
        dev_opt,
        truncated=collector.truncated
        or status2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE),
        solutions_seen=collector.count,
        solve_time_ms=elapsed_ms,
        status=f"phase1={status_name}, phase2={solver2.StatusName(status2)}",
    )


def _build_result(
    dataset: dict,
    assignment: dict[str, list[str]],
    verified_count: int,
    total_deviation: int,
    truncated: bool,
    solutions_seen: int,
    solve_time_ms: int,
    status: str,
) -> dict:
    slots = {s["id"]: s for s in dataset["slots"]}
    frags = {f["id"]: f for f in dataset["fragments"]}

    # 同素材源区间总时长（未核销原因的尽力诊断用）
    material_length: dict[str, int] = defaultdict(int)
    material_present: set[str] = set()
    for f in dataset["fragments"]:
        material_length[f["material_id"]] += f["on_air_end"] - f["on_air_start"]
        material_present.add(f["material_id"])

    verified = []
    unverified = []
    used_fragment_ids: set[str] = set()

    for s in dataset["slots"]:
        seq = assignment.get(s["id"])
        if not seq:
            if s["material_id"] not in material_present:
                reason = "无同素材实播片段"
            elif material_length[s["material_id"]] < s["duration"]:
                reason = "同素材片段总时长不足"
            else:
                reason = "无法在全局约束下拼出满足容差/停顿要求的序列"
            unverified.append({**s, "reason": reason})
            continue

        pieces = []
        prev_end = None
        for order, fid in enumerate(seq):
            f = frags[fid]
            used_fragment_ids.add(fid)
            pause_before = (
                f["on_air_start"] - prev_end if prev_end is not None else None
            )
            pieces.append(
                {
                    "order": order,
                    "fragment_id": fid,
                    "material_id": f["material_id"],
                    "source_start": f["source_start"],
                    "source_end": f["source_end"],
                    "on_air_start": f["on_air_start"],
                    "on_air_end": f["on_air_end"],
                    "length": f["on_air_end"] - f["on_air_start"],
                    "pause_before": pause_before,
                }
            )
            prev_end = f["on_air_end"]

        first_start = frags[seq[0]]["on_air_start"]
        verified.append(
            {
                "slot_id": s["id"],
                "material_id": s["material_id"],
                "planned_start": s["planned_start"],
                "duration": s["duration"],
                "tolerance": s["tolerance"],
                "max_gap": s["max_gap"],
                "first_start": first_start,
                "deviation": first_start - s["planned_start"],
                "fragment_ids": list(seq),
                "fragments": pieces,
            }
        )

    idle_fragments = [
        f for f in dataset["fragments"] if f["id"] not in used_fragment_ids
    ]

    return {
        "verified_count": verified_count,
        "total_deviation": total_deviation,
        "verified": verified,
        "unverified": unverified,
        "idle_fragments": idle_fragments,
        "assignments": {sid: list(seq) for sid, seq in assignment.items()},
        "tie_break_complete": not truncated,
        "solutions_seen": solutions_seen,
        "solve_time_ms": solve_time_ms,
        "solver_status": status,
    }
