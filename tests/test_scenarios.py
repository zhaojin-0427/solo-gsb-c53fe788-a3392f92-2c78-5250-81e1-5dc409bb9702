"""求解器端到端场景测试（不依赖网络）。"""
import sys
sys.path.insert(0, "/workspace")

from app.schemas import validate_dataset
from app.solver import solve

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {extra}")


def run(data):
    d, errs = validate_dataset(data)
    assert not errs, errs
    return d, solve(d)


print("== 1. 单片段完美核销 ==")
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 1000,
         "duration": 500, "tolerance": 100, "max_gap": 0}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 1000,
         "on_air_end": 1500, "source_start": 0, "source_end": 500}],
})
check("核销数=1", r["verified_count"] == 1, r)
check("偏差和=0", r["total_deviation"] == 0)
check("分配 F1", r["assignments"].get("S1") == ["F1"])
check("无闲置", len(r["idle_fragments"]) == 0)

print("== 2. 超容差不核销 ==")
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 1000,
         "duration": 500, "tolerance": 50, "max_gap": 0}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 1100,
         "on_air_end": 1600, "source_start": 0, "source_end": 500}],
})
check("核销数=0", r["verified_count"] == 0)
check("F1 闲置", [f["id"] for f in r["idle_fragments"]] == ["F1"])

print("== 3. 两段拼接 + 停顿允许 ==")
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 0,
         "duration": 1000, "tolerance": 0, "max_gap": 100}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 0,
         "on_air_end": 400, "source_start": 0, "source_end": 400},
        {"id": "F2", "material_id": "M1", "on_air_start": 450,
         "on_air_end": 1050, "source_start": 400, "source_end": 1000}],
})
check("核销数=1", r["verified_count"] == 1, r)
check("序列 F1,F2", r["assignments"]["S1"] == ["F1", "F2"])
v = r["verified"][0]
check("停顿证据=50", v["fragments"][1]["pause_before"] == 50)

print("== 4. 停顿超限不核销 ==")
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 0,
         "duration": 1000, "tolerance": 0, "max_gap": 49}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 0,
         "on_air_end": 400, "source_start": 0, "source_end": 400},
        {"id": "F2", "material_id": "M1", "on_air_start": 450,
         "on_air_end": 1050, "source_start": 400, "source_end": 1000}],
})
check("核销数=0", r["verified_count"] == 0)

print("== 5. 源缺口不核销 ==")
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 0,
         "duration": 1000, "tolerance": 0, "max_gap": 1000}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 0,
         "on_air_end": 400, "source_start": 0, "source_end": 400},
        {"id": "F2", "material_id": "M1", "on_air_start": 400,
         "on_air_end": 1000, "source_start": 500, "source_end": 1100}],
})
check("核销数=0", r["verified_count"] == 0)

print("== 6. 源重叠不核销（总时长虽够）==")
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 0,
         "duration": 1000, "tolerance": 0, "max_gap": 1000}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 0,
         "on_air_end": 600, "source_start": 0, "source_end": 600},
        {"id": "F2", "material_id": "M1", "on_air_start": 600,
         "on_air_end": 1000, "source_start": 400, "source_end": 800},
    ],
})
check("核销数=0", r["verified_count"] == 0)

print("== 7. 全局竞争：一个共享片段两个广告位，最大化位数 ==")
# S1/S2 同素材，都需要 F* 片段。F1 覆盖整个素材，但两个位各需独立片段。
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 0,
         "duration": 500, "tolerance": 0, "max_gap": 0},
        {"id": "S2", "material_id": "M1", "planned_start": 1000,
         "duration": 500, "tolerance": 0, "max_gap": 0}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 0,
         "on_air_end": 500, "source_start": 0, "source_end": 500},
        {"id": "F2", "material_id": "M1", "on_air_start": 1000,
         "on_air_end": 1500, "source_start": 0, "source_end": 500},
    ],
})
check("核销数=2", r["verified_count"] == 2, r)
check("S1<-F1, S2<-F2", r["assignments"] == {"S1": ["F1"], "S2": ["F2"]})

print("== 8. 只能核销一个时，最大化位数后最小化偏差和 ==")
# S1@1000±1000 与 S2@5000±1000 竞争唯一完整片段 F1@1100
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 1000,
         "duration": 500, "tolerance": 5000, "max_gap": 0},
        {"id": "S2", "material_id": "M1", "planned_start": 5000,
         "duration": 500, "tolerance": 5000, "max_gap": 0}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 1100,
         "on_air_end": 1600, "source_start": 0, "source_end": 500}],
})
check("核销数=1", r["verified_count"] == 1)
check("选择偏差小的 S1(100)", set(r["assignments"]) == {"S1"}, r["assignments"])
check("偏差和=100", r["total_deviation"] == 100)

print("== 9. 字典序：位ID z 向量最小（S1 vs S2 同分时弃 S1? 否——取 z 字典序最小=保留 ID 小者）==")
# S1/S2 完全对称竞争，z=(1,0) 优于 (0,1)
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 1000,
         "duration": 500, "tolerance": 0, "max_gap": 0},
        {"id": "S2", "material_id": "M1", "planned_start": 2000,
         "duration": 500, "tolerance": 5000, "max_gap": 0}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 1000,
         "on_air_end": 1500, "source_start": 0, "source_end": 500}],
})
check("保留 S1", set(r["assignments"]) == {"S1"}, r["assignments"])

print("== 10. 字典序：片段 ID 序列最小 ==")
# 两组同素材片段都能核销 S1（源拼满、同时播出→但会播出重叠，故改成先后两套都可行）
# A: FA1[源0-500 播1000-1500] FA2[源500-1000 播1500-2000]
# B: FB1[源0-500 播2000-2500] FB2[源500-1000 播2500-3000]
# S1 planned=1000±2000, max_gap=0；两组都可核销，偏差 A=0, B=1000，二级目标已选 A。
# 构造同分：让 B 首播也=1000，但 B 片段源区间在不同素材？同素材会源重叠——没关系，
# 只要每次只选一组即可。为保证偏差同分，让 B 也是 1000 播出（与 A 播出重叠但不会同时被选）。
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 1000,
         "duration": 1000, "tolerance": 0, "max_gap": 0}],
    "fragments": [
        {"id": "FB1", "material_id": "M1", "on_air_start": 1000,
         "on_air_end": 1500, "source_start": 0, "source_end": 500},
        {"id": "FA1", "material_id": "M1", "on_air_start": 1000,
         "on_air_end": 1500, "source_start": 0, "source_end": 500},
        {"id": "FB2", "material_id": "M1", "on_air_start": 1500,
         "on_air_end": 2000, "source_start": 500, "source_end": 1000},
        {"id": "FA2", "material_id": "M1", "on_air_start": 1500,
         "on_air_end": 2000, "source_start": 500, "source_end": 1000}],
})
check("核销数=1", r["verified_count"] == 1)
check("选 ID 序列字典序最小 FA1,FA2",
      r["assignments"]["S1"] == ["FA1", "FA2"], r["assignments"])
check("未用片段闲置",
      sorted(f["id"] for f in r["idle_fragments"]) == ["FB1", "FB2"])

print("== 11. 播出顺序必须与源顺序一致 ==")
# 源 0-500 的片段在 1500 播、源 500-1000 的片段在 1000 播（倒挂）
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 1000,
         "duration": 1000, "tolerance": 0, "max_gap": 1000}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 1500,
         "on_air_end": 2000, "source_start": 0, "source_end": 500},
        {"id": "F2", "material_id": "M1", "on_air_start": 1000,
         "on_air_end": 1500, "source_start": 500, "source_end": 1000}],
})
check("核销数=0（顺序倒挂）", r["verified_count"] == 0)

print("== 12. 同素材交错片段全局分配，两个位都核销 ==")
# S1 需 0-1000 素材；S2 需 0-600。交错：
# F1: 源0-600 播1000-1600  —— S2 可用
# F2: 源600-1000 播1600-2000 —— S1 尾
# F3: 源0-400 播3000-3400  —— S1 头候选/ S2 候选
# F4: 源400-600 播3400-3600 —— S2 尾候选
# S1=1000±0,gap0: F1+F2 拼满 → 核销
# S2=3000±0: F3+F4 拼满 → 核销，全局无冲突
d, r = run({
    "slots": [
        {"id": "S1", "material_id": "M1", "planned_start": 1000,
         "duration": 1000, "tolerance": 0, "max_gap": 0},
        {"id": "S2", "material_id": "M1", "planned_start": 3000,
         "duration": 600, "tolerance": 0, "max_gap": 0}],
    "fragments": [
        {"id": "F1", "material_id": "M1", "on_air_start": 1000,
         "on_air_end": 1600, "source_start": 0, "source_end": 600},
        {"id": "F2", "material_id": "M1", "on_air_start": 1600,
         "on_air_end": 2000, "source_start": 600, "source_end": 1000},
        {"id": "F3", "material_id": "M1", "on_air_start": 3000,
         "on_air_end": 3400, "source_start": 0, "source_end": 400},
        {"id": "F4", "material_id": "M1", "on_air_start": 3400,
         "on_air_end": 3600, "source_start": 400, "source_end": 600}],
})
check("核销数=2", r["verified_count"] == 2, r)
check("S1=F1,F2 S2=F3,F4",
      r["assignments"] == {"S1": ["F1", "F2"], "S2": ["F3", "F4"]},
      r["assignments"])

print("== 13. 校验：区间长度不等被拒 ==")
d, errs = validate_dataset({
    "slots": [{"id": "S1", "material_id": "M", "planned_start": 0,
               "duration": 10, "tolerance": 0, "max_gap": 0}],
    "fragments": [{"id": "F1", "material_id": "M", "on_air_start": 0,
                   "on_air_end": 10, "source_start": 0, "source_end": 9}],
})
check("返回错误", d is None and any("长度" in e for e in errs), errs)

print("== 14. 校验：负时长/重复ID被拒 ==")
d, errs = validate_dataset({
    "slots": [{"id": "S1", "material_id": "M", "planned_start": 0,
               "duration": 0, "tolerance": -1, "max_gap": 0}],
    "fragments": [
        {"id": "F1", "material_id": "M", "on_air_start": 0,
         "on_air_end": 0, "source_start": 0, "source_end": 5},
        {"id": "F1", "material_id": "M", "on_air_start": 0,
         "on_air_end": 5, "source_start": 0, "source_end": 5}],
})
check("多条错误", d is None and len(errs) >= 4, errs)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
