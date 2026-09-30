"""内置示例：演示重复素材全局分配、交错片段、容差与停顿约束。

S001 与 S002 同为素材 M01，存在多套交错可选拼法；
S003 同素材但最大停顿 200ms，其候选片段间停顿 800ms 因而无法核销；
S004 使用独立素材 M02 正常核销；L010/L011 等为闲置片段。
所有时间单位为整数毫秒。
"""
from __future__ import annotations

SAMPLE_SLOTS = [
    # S001：计划 5000，时长 3000，容差 250
    {"slot_id": "S001", "material_id": "M01", "planned_start": 5000, "duration": 3000,
     "tolerance": 250, "max_pause": 500},
    # S002：同为 M01，计划 12000
    {"slot_id": "S002", "material_id": "M01", "planned_start": 12000, "duration": 3000,
     "tolerance": 600, "max_pause": 500},
    # S003：停顿上限 200ms，无满足条件的拼接
    {"slot_id": "S003", "material_id": "M03", "planned_start": 20000, "duration": 1000,
     "tolerance": 100, "max_pause": 200},
    # S004：单一片段完整覆盖
    {"slot_id": "S004", "material_id": "M02", "planned_start": 24000, "duration": 2000,
     "tolerance": 300, "max_pause": 0},
]


def _seg(sid, mat, a0, a1, s0, s1):
    return {"seg_id": sid, "material_id": mat,
            "air_start": a0, "air_end": a1, "src_start": s0, "src_end": s1}


SAMPLE_SEGMENTS = [
    # —— M01：两套交错片段，可拼成 [0,3000) ——
    _seg("L001", "M01", 4950, 6150, 0, 1200),
    _seg("L002", "M01", 6150, 7200, 1200, 2250),
    _seg("L003", "M01", 7200, 7950, 2250, 3000),
    _seg("L004", "M01", 5100, 6000, 0, 900),
    _seg("L005", "M01", 6050, 7400, 900, 2250),
    _seg("L006", "M01", 7400, 8150, 2250, 3000),
    _seg("L007", "M01", 12000, 13200, 0, 1200),
    _seg("L008", "M01", 13200, 14250, 1200, 2250),
    _seg("L009", "M01", 14250, 15000, 2250, 3000),
    # —— M02：单片段正好 2000ms ——
    _seg("L010", "M02", 24050, 26050, 0, 2000),
    # —— M03：两段停顿 800ms，超过 S003 的 200ms 上限 ——
    _seg("L011", "M03", 20020, 20520, 0, 500),
    _seg("L012", "M03", 21320, 21820, 500, 1000),
    # —— 无计划引用的素材（闲置）——
    _seg("L013", "M99", 30000, 31500, 0, 1500),
]
