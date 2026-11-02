"""Compare same-day model and current-hour estimated AQI across districts."""
from concurrent.futures import ThreadPoolExecutor

from . import aqi_service as aqi
from .data_service import CITIES
from .monitoring_service import monitoring_service
from .prediction_service import prediction_service


def _one(city):
    cur = monitoring_service.current(city)
    if not cur.get("ok") or cur.get("aqi") is None:
        return {"city": city, "ok": False, "error": cur.get("error", "Real-time AQI unavailable")}
    try:
        now = prediction_service.nowcast(city, cur["values"])
    except Exception as e:
        return {"city": city, "ok": False, "error": str(e)}
    rt = float(cur["aqi"])
    return {"city": city, "ok": True,
            "model_aqi": round(now["xgb_aqi"], 1), "estimated_aqi": int(rt),
            "difference": round(abs(now["xgb_aqi"] - rt), 1),
            "dominant": cur.get("dominant"),
            "category": aqi.category(rt), "color": aqi.color(rt),
            "estimate_time": cur.get("estimate_time"),
            "estimate_old": cur.get("estimate_old", False),
            "imputed": now["imputed"], "history_ends": now["basis"]["history_ends"],
            "stale": now["basis"]["stale"]}


def compare_today():
    with ThreadPoolExecutor(max_workers=7) as ex:
        rows = list(ex.map(_one, CITIES))
    return {"rows": rows,
            "note": "Same-day comparison of the XGBoost model (historical training features plus current-hour API pollutants) against CPCB AQI calculated from the same API snapshot. Dates and district match. This is not a multi-day forecast score and does not use physical sensor readings."}


def ranking():
    """Live ranking of all cities by current AQI."""
    with ThreadPoolExecutor(max_workers=7) as ex:
        cur = list(ex.map(monitoring_service.current, CITIES))
    rows = [{"city": c["city"], "aqi": c["aqi"], "category": c["category"], "color": c["color"],
             "dominant": c["dominant"], "estimate_time": c.get("estimate_time"),
             "estimate_old": c.get("estimate_old", False)}
            for c in cur if c.get("ok") and c.get("aqi") is not None]
    failed = [CITIES[i] for i, c in enumerate(cur) if not (c.get("ok") and c.get("aqi") is not None)]
    rows.sort(key=lambda r: r["aqi"], reverse=True)
    return {"rows": rows, "unavailable": failed}
