"""输入数据校验。

输入 JSON 结构：
{
  "channel": "CH1",                      # 可选，频道/计划名称
  "slots": [                             # 广告位（计划）
    {"id": "S1", "material_id": "M1", "planned_start": 0,
     "duration": 1000, "tolerance": 100, "max_gap": 0}
  ],
  "fragments": [                         # 实播片段（日志）
    {"id": "F1", "material_id": "M1",
     "on_air_start": 0, "on_air_end": 500,
     "source_start": 0, "source_end": 500}
  ]
}

所有时间均为整数毫秒；区间一律为半开区间 [start, end)。
"""
from __future__ import annotations

from typing import Any


def _is_int(v: Any) -> bool:
    # bool 是 int 的子类，需显式排除
    return isinstance(v, int) and not isinstance(v, bool)


def _err(errors: list[str], msg: str) -> None:
    errors.append(msg)


def validate_dataset(data: Any) -> tuple[dict | None, list[str]]:
    """返回 (规范化后的数据集, 错误列表)；有错时数据集为 None。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return None, ["请求体必须是 JSON 对象"]

    channel = data.get("channel", "")
    if channel is None:
        channel = ""
    if not isinstance(channel, str):
        _err(errors, "channel 必须是字符串")
        channel = str(channel)

    raw_slots = data.get("slots")
    raw_frags = data.get("fragments")
    if not isinstance(raw_slots, list):
        _err(errors, "slots 必须是数组")
        raw_slots = []
    if not isinstance(raw_frags, list):
        _err(errors, "fragments 必须是数组")
        raw_frags = []

    if len(raw_slots) == 0:
        _err(errors, "slots 至少包含一个广告位")

    slots: list[dict] = []
    seen_slot_ids: set[str] = set()
    for i, s in enumerate(raw_slots):
            where = f"slots[{i}]"
            if not isinstance(s, dict):
                _err(errors, f"{where} 必须是对象")
                continue
            sid = s.get("id")
            mid = s.get("material_id")
            ps, dur, tol, gap = (
                s.get("planned_start"),
                s.get("duration"),
                s.get("tolerance"),
                s.get("max_gap"),
            )
            ok = True
            if not isinstance(sid, str) or not sid.strip():
                _err(errors, f"{where}.id 必须是非空字符串")
                ok = False
            elif sid in seen_slot_ids:
                _err(errors, f"{where}.id 重复: {sid!r}")
                ok = False
            else:
                seen_slot_ids.add(sid)
            if not isinstance(mid, str) or not mid.strip():
                _err(errors, f"{where}.material_id 必须是非空字符串")
                ok = False
            if not _is_int(ps) or ps < 0:
                _err(errors, f"{where}.planned_start 必须是非负整数毫秒")
                ok = False
            if not _is_int(dur) or dur <= 0:
                _err(errors, f"{where}.duration 必须是正整数毫秒")
                ok = False
            if not _is_int(tol) or tol < 0:
                _err(errors, f"{where}.tolerance 必须是非负整数毫秒")
                ok = False
            if not _is_int(gap) or gap < 0:
                _err(errors, f"{where}.max_gap 必须是非负整数毫秒")
                ok = False
            if ok:
                seen_slot_ids.add(sid)
                slots.append(
                    {
                        "id": sid,
                        "material_id": mid,
                        "planned_start": ps,
                        "duration": dur,
                        "tolerance": tol,
                        "max_gap": gap,
                    }
                )

    fragments: list[dict] = []
    seen_frag_ids: set[str] = set()
    for i, f in enumerate(raw_frags):
            where = f"fragments[{i}]"
            if not isinstance(f, dict):
                _err(errors, f"{where} 必须是对象")
                continue
            fid = f.get("id")
            mid = f.get("material_id")
            oa_s, oa_e = f.get("on_air_start"), f.get("on_air_end")
            src_s, src_e = f.get("source_start"), f.get("source_end")
            ok = True
            if not isinstance(fid, str) or not fid.strip():
                _err(errors, f"{where}.id 必须是非空字符串")
                ok = False
            elif fid in seen_frag_ids:
                _err(errors, f"{where}.id 重复: {fid!r}")
                ok = False
            else:
                seen_frag_ids.add(fid)
            if not isinstance(mid, str) or not mid.strip():
                _err(errors, f"{where}.material_id 必须是非空字符串")
                ok = False
            int_fields = {
                "on_air_start": oa_s,
                "on_air_end": oa_e,
                "source_start": src_s,
                "source_end": src_e,
            }
            for name, v in int_fields.items():
                if not _is_int(v) or v < 0:
                    _err(errors, f"{where}.{name} 必须是非负整数毫秒")
                    ok = False
            if ok:
                if oa_e <= oa_s:
                    _err(errors, f"{where} 播出区间 [{oa_s}, {oa_e}) 长度必须大于零")
                    ok = False
                if src_e <= src_s:
                    _err(errors, f"{where} 素材源区间 [{src_s}, {src_e}) 长度必须大于零")
                    ok = False
                if ok and (oa_e - oa_s) != (src_e - src_s):
                    _err(
                        errors,
                        f"{where} 播出区间长度 {oa_e - oa_s} 与素材源区间长度 "
                        f"{src_e - src_s} 不相等",
                    )
                    ok = False
            if ok:
                seen_frag_ids.add(fid)
                fragments.append(
                    {
                        "id": fid,
                        "material_id": mid,
                        "on_air_start": oa_s,
                        "on_air_end": oa_e,
                        "source_start": src_s,
                        "source_end": src_e,
                    }
                )

    if errors:
        return None, errors

    return {"channel": channel, "slots": slots, "fragments": fragments}, []
