# -*- coding: utf-8 -*-
"""محرك التقييم الهجين (قواعد + ذكاء اصطناعي)"""
import math
from typing import Optional
from .data import CROPS, FAMILIES, INCOMPATIBLE, GOOD_ROTATIONS, MONTHS_AR
from .time_utils import timing_penalty, resolve_year, timing_status


def check_rotation(prev: str, crop_name: str) -> dict:
    """التحقق من توافق الدورة الزراعية"""
    if not prev:
        return {"valid": True, "msg": ""}
    if prev == crop_name:
        return {"valid": False, "msg": f"لا يُزرع {crop_name} بعد نفسه"}
    pf = FAMILIES.get(prev)
    cf = FAMILIES.get(crop_name)
    if pf and cf and cf in INCOMPATIBLE.get(pf, []):
        return {"valid": False, "msg": f"تعارض عائلة نباتية: {crop_name} لا يُزرع بعد {prev}"}
    if pf and cf and cf in GOOD_ROTATIONS.get(pf, []):
        return {"valid": True, "msg": f"دوران زراعي مثالي ✓"}
    return {"valid": True, "msg": "دوران مقبول"}


def rule_score(crop: dict, wd: dict, req, weather_temp) -> int:
    """نظام التقييم القائم على القواعد (0-100)"""
    score = 0
    wmap = {"منخفضة جداً":0,"منخفضة":1,"متوسطة":2,"عالية":3}
    user_w = wmap.get(req.water, 1)
    crop_w = wmap.get(crop["مياه"], 1)
    wdiff = abs(user_w - crop_w)
    score += 25 if wdiff == 0 else (15 if wdiff == 1 else 4)

    score += 25 if wd["تربة"] in crop["تربة"] else 5

    r = wd.get("avgRainfall", 300)
    if r >= crop["rainfallMin"] and r <= crop["rainfallMax"]: score += 8
    elif r >= crop["rainfallMin"] * 0.6: score += 4

    pen = timing_penalty(crop["plantIdx"], req.plant_month)
    score += max(0, 20 - pen)

    diff_map = {"سهل":0,"متوسط":1,"خبير":2}
    exp_map  = {"مبتدئ":0,"متوسط":1,"خبير":2}
    cd = diff_map.get(crop["صعوبة"], 0)
    ue = exp_map.get(req.experience, 0)
    score += 12 if ue >= cd else (8 if ue == cd - 1 else 1)

    if req.goal == "تصدير" and crop["تصدير"]: score += 10
    elif req.goal == "بيع" and crop["إنتاج"] >= 5: score += 10
    elif req.goal in ["اكتفاء","كلاهما"]: score += 10
    else: score += 5

    if "صحراوية" in wd["منطقة"] and crop["مياه"] in ["منخفضة جداً","منخفضة"]: score += 5
    elif "شمالية" in wd["منطقة"] and crop["مياه"] == "عالية": score += 5
    else: score += 2

    return min(max(score, 0), 100)


def ml_score(crop: dict, wd: dict, req, weather_temp) -> int:
    """نظام التقييم الشبيه بالذكاء الاصطناعي (0-100)"""
    wmap = {"منخفضة جداً":0,"منخفضة":0.33,"متوسطة":0.66,"عالية":1.0}

    soil_match = 1.0 if wd["تربة"] in crop["تربة"] else 0.12
    water_sim  = 1 - abs(wmap.get(req.water, 0.5) - wmap.get(crop["مياه"], 0.5))
    yield_n    = min(math.log1p(crop["إنتاج"]) / math.log1p(50), 1.0)

    pen = timing_penalty(crop["plantIdx"], req.plant_month)
    season_fit = max(0, 1 - pen / 30)

    temp_fit = 0.65
    if weather_temp is not None:
        if crop["tempMin"] <= weather_temp <= crop["tempMax"]:
            temp_fit = 1.0
        else:
            overshoot = max(0, weather_temp - crop["tempMax"], crop["tempMin"] - weather_temp)
            temp_fit = max(0.1, 1 - overshoot / 15)

    rain_fit = 0.6
    r = wd.get("avgRainfall", 300)
    if r >= crop["rainfallMin"] and r <= crop["rainfallMax"]:
        rain_fit = 1.0
    else:
        gap = max(0, crop["rainfallMin"] - r, r - crop["rainfallMax"])
        rain_fit = max(0.1, 1 - gap / 400)

    rot_bonus = 0.0
    if req.prev_crop:
        if req.prev_crop in crop.get("rotGood", []):
            rot_bonus = 0.12
        elif req.prev_crop in crop.get("rotBad", []):
            rot_bonus = -0.15

    region_fit = 0.6
    if "صحراوية" in wd["منطقة"] and crop["مياه"] in ["منخفضة جداً","منخفضة"]:
        region_fit = 1.0
    elif "شمالية" in wd["منطقة"] and crop["مياه"] == "عالية":
        region_fit = 1.0
    elif "صحراوية" in wd["منطقة"] and crop["مياه"] == "عالية":
        region_fit = 0.2
    elif "شبه صحراوية" in wd["منطقة"] and crop["مياه"] in ["منخفضة","متوسطة"]:
        region_fit = 0.85

    diff_map2 = {"سهل":1.0,"متوسط":0.7,"خبير":0.4}
    exp_map2  = {"مبتدئ":0.3,"متوسط":0.7,"خبير":1.0}
    exp_fit = max(0, 1 - abs(exp_map2.get(req.experience, 0.5) - (1 - diff_map2.get(crop["صعوبة"], 0.5))))

    if req.goal == "تصدير":
        goal_fit = 1.0 if crop["تصدير"] else 0.25
    elif req.goal == "بيع":
        goal_fit = min(math.log1p(crop["إنتاج"]) / math.log1p(40), 1.0)
    else:
        goal_fit = 0.8

    raw = (
        soil_match * 0.22 +
        water_sim  * 0.17 +
        season_fit * 0.18 +
        yield_n    * 0.10 +
        temp_fit   * 0.10 +
        rain_fit   * 0.08 +
        region_fit * 0.07 +
        exp_fit    * 0.05 +
        goal_fit   * 0.03
    ) + rot_bonus

    return round(min(max(raw, 0), 1) * 100)


def hybrid_score(rs: int, ms: int) -> int:
    """دمج نتيجتي القواعد والذكاء الاصطناعي"""
    return round(rs * 0.58 + ms * 0.42)


def build_explanation(crop_name: str, crop: dict, wd: dict, req, weather_temp) -> list:
    """بناء شرح مفصل لسبب توصية المحصول"""
    items = []
    wL = {"منخفضة جداً":"شحيحة جداً","منخفضة":"محدودة","متوسطة":"معتدلة","عالية":"وفيرة"}

    if wd["تربة"] in crop["تربة"]:
        items.append({"type":"good","text":f"تربة {wd['تربة']} مثالية — الجذور تتأقلم بامتياز"})
    else:
        items.append({"type":"warn","text":f"تربة {wd['تربة']} غير مثالية — أضف سماداً عضوياً وحسّن البنية"})

    if crop["مياه"] == req.water or (req.water == "متوسطة" and crop["مياه"] == "منخفضة"):
        items.append({"type":"good","text":f"الري ({wL.get(req.water,'')}) يتوافق مع احتياج {crop_name}"})
    elif req.water == "عالية" and crop["مياه"] == "منخفضة":
        items.append({"type":"warn","text":f"ري زائد قد يسبب تعفن الجذور — استخدم ري موجّه أو بالتنقيط"})
    else:
        items.append({"type":"warn","text":f"{crop_name} يحتاج ري {crop['مياه']} — فكّر في الري بالتنقيط"})

    ts = timing_status(crop["plantIdx"], req.plant_month)
    t = "good" if ts["type"] in ["optimal","near"] else "warn"
    items.append({"type": t, "text": ts["msg"]})

    resolved_year = resolve_year(req.plant_month)
    items.append({"type":"info","text":f"دورة النمو: {crop['دورة']} يوم — زراعة {MONTHS_AR[req.plant_month]} {resolved_year} ← حصاد {crop['حصاد']}"})

    diff_map = {"سهل":"مناسب للجميع","متوسط":"يتطلب خبرة متوسطة","خبير":"يتطلب خبرة عالية"}
    if req.experience == "خبير":
        items.append({"type":"good","text":f"{diff_map.get(crop['صعوبة'],'')} — بخبرتك ستحقق أعلى إنتاجية"})
    elif req.experience == "مبتدئ" and crop["صعوبة"] == "خبير":
        items.append({"type":"warn","text":f"يحتاج خبرة عالية — ابدأ بكميات صغيرة أو استعن بمرشد زراعي"})
    else:
        items.append({"type":"info","text":f"{diff_map.get(crop['صعوبة'],'')} — مناسب لمستوى خبرتك"})

    if weather_temp is not None:
        if 15 <= weather_temp <= 28:
            items.append({"type":"good","text":f"الحرارة {weather_temp}°م مناسبة لنمو {crop_name}"})
        elif weather_temp > 38:
            items.append({"type":"warn","text":f"حرارة {weather_temp}°م مرتفعة — أضف تغطية ظلية وزد الري صباحاً"})
        elif weather_temp < 10:
            items.append({"type":"warn","text":f"حرارة {weather_temp}°م منخفضة — احمِ {crop_name} من الصقيع"})
        else:
            items.append({"type":"info","text":f"الحرارة الحالية {weather_temp}°م — مقبولة"})

    if req.goal == "تصدير" and crop["تصدير"]:
        items.append({"type":"good","text":f"محصول تصديري — مطلوب في الأسواق الجزائرية والأوروبية"})
    elif req.goal == "بيع" and crop["إنتاج"] >= 10:
        items.append({"type":"good","text":f"إنتاجية عالية ({crop['إنتاج']} طن/هكتار) — مردود تجاري ممتاز"})
    elif req.goal == "اكتفاء":
        items.append({"type":"info","text":f"مناسب للاكتفاء الذاتي وتأمين غذاء الأسرة"})

    return items