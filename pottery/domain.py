"""纯计算：烧制程序解析、时长、温度曲线、冷却曲线、时段重叠。"""
from __future__ import annotations

import json
from datetime import datetime

AMBIENT_C = 25.0  # 室温


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def fmt_dt(s: str | None) -> str:
    if not s:
        return "—"
    return parse_dt(s).strftime("%m-%d %H:%M")


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse_segments(raw) -> list[dict]:
    """程序段：[{"target": 600, "rate": 150}, {"hold": 30}, ...]

    rate 段：以 rate °C/h 升（降）至 target；hold 段：保温 hold 分钟。
    """
    segs = json.loads(raw) if isinstance(raw, str) else list(raw)
    for seg in segs:
        if "rate" in seg:
            if "target" not in seg:
                raise ValueError("rate 段缺少 target")
            if float(seg["rate"]) <= 0:
                raise ValueError("rate 必须为正")
        elif "hold" not in seg:
            raise ValueError("程序段需要 rate 或 hold")
    return segs


def program_duration_minutes(segments: list[dict]) -> float:
    temp = AMBIENT_C
    minutes = 0.0
    for seg in segments:
        if "rate" in seg:
            target = float(seg["target"])
            minutes += abs(target - temp) / float(seg["rate"]) * 60.0
            temp = target
        else:
            minutes += float(seg["hold"])
    return minutes


def program_max_temp(segments: list[dict]) -> float:
    temps = [float(s["target"]) for s in segments if "target" in s]
    return max(temps) if temps else AMBIENT_C


def program_final_temp(segments: list[dict]) -> float:
    temps = [float(s["target"]) for s in segments if "target" in s]
    return temps[-1] if temps else AMBIENT_C


def profile_points(segments: list[dict]) -> list[tuple[float, float]]:
    """阶梯曲线折点：[(累计分钟, 温度)]。"""
    points = [(0.0, AMBIENT_C)]
    temp, minutes = AMBIENT_C, 0.0
    for seg in segments:
        if "rate" in seg:
            target = float(seg["target"])
            minutes += abs(target - temp) / float(seg["rate"]) * 60.0
            temp = target
        else:
            minutes += float(seg["hold"])
        points.append((minutes, temp))
    return points


def temp_at(segments: list[dict], elapsed_min: float) -> tuple[float, str]:
    """点火后 elapsed_min 分钟时的炉温与阶段。"""
    temp, minutes = AMBIENT_C, 0.0
    for seg in segments:
        if "rate" in seg:
            target = float(seg["target"])
            dur = abs(target - temp) / float(seg["rate"]) * 60.0
            if elapsed_min <= minutes + dur:
                f = (elapsed_min - minutes) / dur if dur > 0 else 1.0
                return temp + (target - temp) * max(0.0, f), ("升温" if target > temp else "降温")
            minutes += dur
            temp = target
        else:
            dur = float(seg["hold"])
            if elapsed_min <= minutes + dur:
                return temp, "保温"
            minutes += dur
    return temp, "保温"


def cooling_temp(end_temp: float, cooling_hours: float, elapsed_min: float) -> float:
    """烧完后线性冷却至室温。"""
    total = cooling_hours * 60.0
    if total <= 0 or elapsed_min >= total:
        return AMBIENT_C
    return end_temp + (AMBIENT_C - end_temp) * (elapsed_min / total)


def outage_temp(start_temp: float, elapsed_min: float) -> float:
    """停电后炉温自然衰减（约 3 小时降至室温）。"""
    total = 180.0
    if elapsed_min >= total:
        return AMBIENT_C
    return start_temp + (AMBIENT_C - start_temp) * (elapsed_min / total)


def ranges_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """半开区间重叠：首尾相接不算冲突。"""
    return a_start < b_end and b_start < a_end
