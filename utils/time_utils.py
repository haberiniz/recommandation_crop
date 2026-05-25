# -*- coding: utf-8 -*-
"""دوال التوقيت والموسم الزراعي"""
from datetime import datetime
from .data import MONTHS_AR


def resolve_year(chosen_month_idx: int) -> int:
    """تحديد السنة المناسبة للزراعة بناءً على الشهر المختار"""
    t = datetime.now()
    current_month = t.month - 1  # 0-based
    if chosen_month_idx >= current_month:
        return t.year
    return t.year + 1


def timing_penalty(crop_plant_idx: int, user_month_idx: int) -> int:
    """حساب عقوبة التوقيت بناءً على الفرق بين الشهر المثالي والمختار"""
    diff = min(abs(crop_plant_idx - user_month_idx), 12 - abs(crop_plant_idx - user_month_idx))
    if diff == 0: return 0
    if diff == 1: return 5
    if diff == 2: return 12
    if diff == 3: return 20
    return 28 + diff * 3


def is_plantable_window(crop_idx: int, user_idx: int) -> bool:
    """التحقق مما إذا كان المحصول قابل للزراعة في الشهر المختار (±3 أشهر)"""
    diff = min(abs(crop_idx - user_idx), 12 - abs(crop_idx - user_idx))
    return diff <= 3


def timing_status(crop_idx: int, user_idx: int) -> dict:
    """إرجاع حالة التوقيت مع رسالة توضيحية"""
    current_month = datetime.now().month - 1
    diff = min(abs(crop_idx - user_idx), 12 - abs(crop_idx - user_idx))
    chosen_is_past = user_idx < current_month
    resolved_year = resolve_year(user_idx)
    crop_month_name = MONTHS_AR[crop_idx]
    user_month_name = MONTHS_AR[user_idx]

    if diff == 0:
        if user_idx == current_month:
            return {"type": "optimal", "icon": "✅", "msg": f"الشهر الحالي ({user_month_name}) هو الوقت المثالي تماماً"}
        if chosen_is_past:
            return {"type": "future", "icon": "📅", "msg": f"الزراعة في {user_month_name} {resolved_year} — الموسم القادم"}
        return {"type": "future", "icon": "📅", "msg": f"الزراعة في {user_month_name} {resolved_year}"}
    if diff <= 1:
        return {"type": "near", "icon": "📅", "msg": f"الموعد المثالي: {crop_month_name} — أنت اخترت {user_month_name} (فارق بسيط مقبول)"}
    if chosen_is_past:
        return {"type": "future", "icon": "🔄", "msg": f"الموعد المثالي: {crop_month_name} — اخترت {user_month_name} {resolved_year} (الموسم القادم)"}
    return {"type": "warn", "icon": "⚠️", "msg": f"الموعد المثالي: {crop_month_name} — أنت اخترت {user_month_name} (فارق {diff} أشهر)"}