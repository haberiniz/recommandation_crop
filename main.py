# -*- coding: utf-8 -*-
"""
🌾 نظام التوصيات الزراعية الجزائري
FastAPI Backend for AgriPAI - Deploy on Render
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
import requests
from datetime import datetime

from utils.data import WILAYAS, CROPS, MONTHS_AR, FAMILIES
from utils.time_utils import resolve_year, timing_status, is_plantable_window

import sys
if sys.version_info < (3, 11):
    print(f"⚠️  تحذير: هذا التطبيق مصمم لـ Python 3.11+، أنت تستخدم {sys.version}")
def timing_penalty(plant_idx: int, req_month: int) -> int:
    """قم بتقدير عقوبة التوقيت بالأيام بين الشهر المثالي وشهر الزراعة المطلوب.
    تُرجع قيمة بين 0 و30 (أكبر اختلاف يعادل عقوبة 30 يوم).
    """
    # حساب الفرق بالشهور بأخذ المسافة الدائرية الدنيا
    diff = abs((req_month - plant_idx) % 12)
    diff = min(diff, 12 - diff)
    days = diff * 30
    return min(days, 30)
from utils.scoring import (
    rule_score, ml_score, hybrid_score, 
    check_rotation, build_explanation
)

app = FastAPI(
    title="🌾 نظام التوصيات الزراعية الجزائري",
    description="API ذكية لتقديم توصيات زراعية مخصصة للولايات الجزائرية الـ58",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ══════════════════════════════════════════════════════════
# CORS Middleware
# ══════════════════════════════════════════════════════════
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # في الإنتاج: استبدل بـ ["https://your-app.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════
# Request Model
# ══════════════════════════════════════════════════════════
class FarmRequest(BaseModel):
    wilaya: str = Field(..., description="اسم الولاية الجزائرية", example="الجزائر")
    area: float = Field(..., gt=0, description="مساحة الأرض بالهكتار", example=2.5)
    plant_month: int = Field(..., ge=0, le=11, description="شهر الزراعة (0=يناير ... 11=ديسمبر)", example=2)
    prev_crop: Optional[str] = Field(default="", description="المحصول السابق للدورة الزراعية", example="القمح الصلب")
    category: Optional[str] = Field(default="", description="فئة المحصول المطلوبة", example="خضروات")
    water: str = Field(..., description="مستوى توفر المياه", example="متوسطة")
    goal: str = Field(..., description="الهدف من الزراعة", example="بيع")
    experience: str = Field(..., description="مستوى خبرة المزارع", example="متوسط")


# ══════════════════════════════════════════════════════════
# Response Models
# ══════════════════════════════════════════════════════════
class CropRecommendation(BaseModel):
    name: str
    score: int
    rule_score: int
    ml_score: int
    yield_total: float
    yield_per_ha: float
    cycle_days: int
    category: str
    difficulty: str
    water_need: str
    plant_month: str
    harvest_month: str
    resolve_year: int
    timing: dict
    rotation: dict
    diseases: List[str]
    exportable: bool
    price_dzd_per_ton: int
    soil_match: bool
    explanation: List[dict]
    breakdown: dict


class RecommendationResponse(BaseModel):
    wilaya: str
    region: str
    soil: str
    rainfall: str
    weather_temp: Optional[float]
    plant_month_name: str
    area: float
    goal: str
    water: str
    experience: str
    prev_crop: str
    top_crops: List[CropRecommendation]
    total_candidates: int


# ══════════════════════════════════════════════════════════
# API Endpoints
# ══════════════════════════════════════════════════════════

@app.get("/", tags=["Root"])
def root():
    """نقطة البداية للتحقق من عمل الـAPI"""
    return {
        "status": "ok",
        "message": "🌾 نظام التوصيات الزراعية الجزائري v2.0",
        "endpoints": {
            "GET /wilayas": "قائمة الولايات الجزائرية",
            "GET /crops": "قائمة المحاصيل المتاحة",
            "POST /recommend": "الحصول على التوصيات الذكية"
        }
    }


@app.get("/wilayas", tags=["Data"], response_model=List[dict])
def get_wilayas():
    """إرجاع قائمة الولايات الجزائرية الـ58 مع معلومات أساسية"""
    return sorted(
        [
            {
                "name": k,
                "code": v["رقم"],
                "region": v["منطقة"],
                "soil": v["تربة"],
                "rainfall": v["أمطار"]
            }
            for k, v in WILAYAS.items()
        ],
        key=lambda x: x["code"]
    )


@app.get("/crops", tags=["Data"], response_model=List[str])
def get_crops():
    """إرجاع قائمة جميع المحاصيل المدعومة"""
    return sorted(list(CROPS.keys()))


@app.get("/crops/{category}", tags=["Data"], response_model=List[str])
def get_crops_by_category(category: str):
    """إرجاع محاصيل فئة معينة"""
    return sorted([name for name, data in CROPS.items() if data["فئة"] == category])


@app.post("/recommend", tags=["AI"], response_model=RecommendationResponse)
def recommend(req: FarmRequest):
    """
    🎯 نقطة النهاية الرئيسية: الحصول على أفضل 3 توصيات زراعية
    
    المدخلات:
    - wilaya: الولاية الجزائرية
    - area: المساحة بالهكتار
    - plant_month: شهر الزراعة (0-11)
    - prev_crop: المحصول السابق (اختياري)
    - category: فئة المحصول المطلوبة (اختياري)
    - water: مستوى المياه (منخفضة جداً/منخفضة/متوسطة/عالية)
    - goal: الهدف (اكتفاء/بيع/كلاهما/تصدير)
    - experience: الخبرة (مبتدئ/متوسط/خبير)
    
    المخرجات:
    - أفضل 3 محاصيل مع درجات التقييم والشرح المفصل
    """
    
    # التحقق من صحة الولاية
    if req.wilaya not in WILAYAS:
        raise HTTPException(
            status_code=400,
            detail=f"الولاية '{req.wilaya}' غير موجودة. استخدم GET /wilayas للحصول على القائمة"
        )

    wd = WILAYAS[req.wilaya]

    # ══════════════════════════════════════════════════════
    # جلب بيانات الطقس الحية من Open-Meteo
    # ══════════════════════════════════════════════════════
    weather_temp = None
    try:
        url = (f"https://api.open-meteo.com/v1/forecast"
               f"?latitude={wd['lat']}&longitude={wd['lng']}"
               f"&current=temperature_2m&timezone=Africa/Algiers")
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            data = r.json()
            weather_temp = data.get("current", {}).get("temperature_2m")
    except Exception:
        pass  # فشل جلب الطقس لا يوقف التوصيات

    # ══════════════════════════════════════════════════════
    # تقييم جميع المحاصيل
    # ══════════════════════════════════════════════════════
    scored = []
    
    for crop_name, crop in CROPS.items():
        # فلتر الفئة
        if req.category and crop["فئة"] != req.category:
            continue

        # فحص الدورة الزراعية
        rot = check_rotation(req.prev_crop, crop_name)
        if not rot["valid"]:
            continue

        # فحص نافذة الزراعة (قاعدة صارمة: ±3 أشهر من الشهر المثالي)
        if not is_plantable_window(crop["plantIdx"], req.plant_month):
            continue

        # حساب الدرجات
        rs = rule_score(crop, wd, req, weather_temp)
        ms = ml_score(crop, wd, req, weather_temp)
        hs = hybrid_score(rs, ms)

        scored.append({
            "name": crop_name,
            "score": hs,
            "rule_score": rs,
            "ml_score": ms,
            "yield_total": round(crop["إنتاج"] * req.area, 2),
            "yield_per_ha": crop["إنتاج"],
            "cycle_days": crop["دورة"],
            "category": crop["فئة"],
            "difficulty": crop["صعوبة"],
            "water_need": crop["مياه"],
            "plant_month": MONTHS_AR[crop["plantIdx"]],
            "harvest_month": crop["حصاد"],
            "resolve_year": resolve_year(req.plant_month),
            "timing": timing_status(crop["plantIdx"], req.plant_month),
            "rotation": rot,
            "diseases": crop["أمراض"],
            "exportable": crop["تصدير"],
            "price_dzd_per_ton": crop["سعر"],
            "soil_match": wd["تربة"] in crop["تربة"],
            "explanation": build_explanation(crop_name, crop, wd, req, weather_temp),
            "breakdown": {
                "soil":   100 if wd["تربة"] in crop["تربة"] else 22,
                "water":  round((1 - abs(
                    {"منخفضة جداً":0,"منخفضة":1,"متوسطة":2,"عالية":3}.get(req.water,1) - 
                    {"منخفضة جداً":0,"منخفضة":1,"متوسطة":2,"عالية":3}.get(crop["مياه"],1)
                ) / 3) * 100),
                "season": max(0, round((1 - timing_penalty(crop["plantIdx"], req.plant_month) / 30) * 100)),
                "experience": max(0, round((1 - abs(
                    {"مبتدئ":0,"متوسط":1,"خبير":2}.get(req.experience,0) - 
                    {"سهل":0,"متوسط":1,"خبير":2}.get(crop["صعوبة"],0)
                ) / 2) * 100)),
            }
        })

    # ══════════════════════════════════════════════════════
    #Fallback: إذا لم نجد نتائج، نزيل قيد نافذة الزراعة
    # ══════════════════════════════════════════════════════
    if not scored:
        for crop_name, crop in CROPS.items():
            if req.category and crop["فئة"] != req.category:
                continue
            rot = check_rotation(req.prev_crop, crop_name)
            if not rot["valid"]:
                continue
            rs = rule_score(crop, wd, req, weather_temp)
            ms = ml_score(crop, wd, req, weather_temp)
            hs = hybrid_score(rs, ms)
            scored.append({
                "name": crop_name, "score": hs, "rule_score": rs, "ml_score": ms,
                "yield_total": round(crop["إنتاج"] * req.area, 2), "yield_per_ha": crop["إنتاج"],
                "cycle_days": crop["دورة"], "category": crop["فئة"], "difficulty": crop["صعوبة"],
                "water_need": crop["مياه"], "plant_month": MONTHS_AR[crop["plantIdx"]],
                "harvest_month": crop["حصاد"], "resolve_year": resolve_year(req.plant_month),
                "timing": timing_status(crop["plantIdx"], req.plant_month),
                "rotation": rot, "diseases": crop["أمراض"], "exportable": crop["تصدير"],
                "price_dzd_per_ton": crop["سعر"], "soil_match": wd["تربة"] in crop["تربة"],
                "explanation": build_explanation(crop_name, crop, wd, req, weather_temp),
                "breakdown": {"soil": 100 if wd["تربة"] in crop["تربة"] else 22, "water": 50, "season": 50, "experience": 50}
            })

    # ══════════════════════════════════════════════════════
    # الترتيب والاختيار مع التنوع
    # ══════════════════════════════════════════════════════
    scored.sort(key=lambda x: (x["score"], x["yield_total"]), reverse=True)

    # اختيار أفضل 3 مع ضمان التنوع (عائلة + فئة مختلفة)
    top = []
    used_fam = set()
    used_cat = set()
    
    # الجولة 1: تنوع صارم
    for item in scored:
        if len(top) >= 3: break
        fam = FAMILIES.get(item["name"], "")
        cat = item["category"]
        if fam not in used_fam and cat not in used_cat:
            top.append(item); used_fam.add(fam); used_cat.add(cat)
    
    # الجولة 2: تنوع العائلة فقط
    for item in scored:
        if len(top) >= 3: break
        fam = FAMILIES.get(item["name"], "")
        if fam not in used_fam:
            top.append(item); used_fam.add(fam)
    
    # الجولة 3: ملء الفراغات
    for item in scored:
        if len(top) >= 3: break
        if item not in top:
            top.append(item)

    return {
        "wilaya": req.wilaya,
        "region": wd["منطقة"],
        "soil": wd["تربة"],
        "rainfall": wd["أمطار"],
        "weather_temp": weather_temp,
        "plant_month_name": MONTHS_AR[req.plant_month],
        "area": req.area,
        "goal": req.goal,
        "water": req.water,
        "experience": req.experience,
        "prev_crop": req.prev_crop,
        "top_crops": top,
        "total_candidates": len(scored),
    }


# ══════════════════════════════════════════════════════════
# Health Check Endpoint (مهم لـ Render)
# ══════════════════════════════════════════════════════════
@app.get("/health", tags=["System"])
def health_check():
    """نقطة فحص الصحة لـ Render Load Balancer"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# ══════════════════════════════════════════════════════════
# Error Handlers
# ══════════════════════════════════════════════════════════
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return {"error": "خطأ داخلي في الخادم", "detail": str(exc)}