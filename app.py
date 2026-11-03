"""AIRWISE - Karnataka air quality: monitoring, prediction, source inference, policy analysis."""
import os
import hmac
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

from services.data_service import data_service, CITY_COORDS, CITIES, DATA_DIR, resolve_city
from services.freshness import freshness
from services.monitoring_service import monitoring_service
from services.prediction_service import prediction_service
from services import comparison_service, source_service
from services.policy_service import policy_service

app = Flask(__name__)
app.json.sort_keys = False


# ------------------------------------------------------------------ helpers
def city_or_404(name):
    c = resolve_city(name)
    if not c:
        return None, (jsonify({"ok": False, "error": f"'{name}' is not an AIRWISE district. Available: {', '.join(CITIES)}"}), 404)
    return c, None


def err(msg, code=500):
    return jsonify({"ok": False, "error": str(msg)}), code


# ------------------------------------------------------------------ pages
@app.route("/")
def index():
    return render_template("index.html", page="home", cities=CITIES)


@app.route("/monitoring")
def monitoring():
    return render_template("monitoring.html", page="monitoring", cities=CITIES)


@app.route("/prediction")
def prediction():
    return render_template("prediction.html", page="prediction", cities=CITIES)


@app.route("/insights")
def insights():
    return render_template("insights.html", page="insights", cities=CITIES)


@app.route("/sensors")
def sensors():
    return render_template("sensors.html", page="sensors", cities=CITIES)


@app.route("/policy")
def policy():
    return render_template("policy.html", page="policy", cities=CITIES)


# ------------------------------------------------------------------ API: meta
@app.route("/api/cities")
def api_cities():
    return jsonify([{"name": c, "lat": CITY_COORDS[c][0], "lon": CITY_COORDS[c][1]} for c in CITIES])


@app.route("/api/health")
def api_health():
    return jsonify({
        "history_loaded": data_service.available(),
        "history": data_service.summary() if data_service.available() else None,
        "model": prediction_service.status(),
        "policy_files": policy_service.overview(),
        "sensors": monitoring_service.sensor_status(),
    })


# ------------------------------------------------------------------ API: monitoring
@app.route("/api/realtime/<city>")
def api_realtime(city):
    c, e = city_or_404(city)
    if e: return e
    res = monitoring_service.current(c)
    return jsonify(res), (200 if res.get("ok") else 502)


@app.route("/api/ranking")
def api_ranking():
    return jsonify(comparison_service.ranking())


@app.route("/api/station-ranking")
def api_station_ranking():
    rows = []
    for city in CITIES:
        station = data_service.latest_station_reading(city)
        rows.append({"city": city, "station": station})
    return jsonify({"rows": rows})


@app.route("/api/data-status")
def api_data_status():
    districts = {}
    for city in CITIES:
        last_date = data_service.data_through(city)
        districts[city] = {
            "last_measured_date": last_date.strftime("%Y-%m-%d") if last_date is not None else None,
            **freshness(last_date),
            "live_feed_fetch_time": monitoring_service.last_success_time(city),
        }
    return jsonify({"districts": districts})


@app.route("/api/history/<city>")
def api_history(city):
    c, e = city_or_404(city)
    if e: return e
    if not data_service.available():
        return err("Historical data not loaded. Run prepare_data.py", 503)
    days = max(7, min(request.args.get("days", 90, type=int), 730))
    return jsonify({"ok": True, "city": c, "trend": data_service.trend(c, days),
                    "monthly": data_service.monthly_profile(c),
                    "latest_station": data_service.latest_station_reading(c)})


@app.route("/api/live-log/<city>")
def api_live_log(city):
    c, e = city_or_404(city)
    if e: return e
    return jsonify({"ok": True, "city": c, "points": monitoring_service.live_log(c, request.args.get("hours", 48, type=int))})


@app.route("/api/sensors/reading", methods=["POST"])
def api_sensor_reading():
    key = os.getenv("SENSOR_API_KEY", "")
    sent = request.headers.get("X-API-Key", "")
    if not key or not hmac.compare_digest(key, sent):
        return err("Invalid or missing X-API-Key", 401)
    body = request.get_json(silent=True) or {}
    c = resolve_city(body.get("district") or body.get("city"))
    if not c:
        return err("Unknown 'district'", 400)
    try:
        stored = monitoring_service.ingest_sensor(c, body.get("device_id"), body)
    except ValueError as ex:
        return err(ex, 400)
    return jsonify({"ok": True, "district": c, "stored": stored})


@app.route("/api/sensors/export")
def api_sensors_export():
    city = request.args.get("city")
    if city:
        city, e = city_or_404(city)
        if e: return e
    limit = request.args.get("limit", 5000, type=int)
    return jsonify(monitoring_service.export_readings(city, limit))


@app.route("/api/sensors/<city>")
def api_sensors_city(city):
    c, e = city_or_404(city)
    if e: return e
    latest = monitoring_service.sensor_current(c)
    hours = max(1, min(request.args.get("hours", 48, type=int), 168))
    return jsonify({
        "ok": True,
        "city": c,
        "latest": latest,
        "points": monitoring_service.sensor_log(c, hours),
        "status": monitoring_service.sensor_status(),
    })


# ------------------------------------------------------------------ API: prediction
@app.route("/api/predict/forecast/<city>")
def api_forecast(city):
    c, e = city_or_404(city)
    if e: return e
    if not data_service.available():
        return err("Historical data not loaded. Run prepare_data.py", 503)
    try:
        res = prediction_service.forecast(
            c,
            request.args.get("days", 7, type=int),
        )
        res["ok"] = True
        res["known_day_validation"] = prediction_service.status()["known_day_validation"]
        return jsonify(res)
    except ValueError as ex:
        return err(ex, 409)
    except Exception as ex:
        return err(ex)


@app.route("/api/predict/outlook")
def api_district_outlook():
    if not data_service.available():
        return err("Historical data not loaded. Run prepare_data.py", 503)
    days = max(1, min(request.args.get("days", 7, type=int), 7))

    def _one(city):
        try:
            res = prediction_service.forecast(city, days)
            return {"ok": True, "city": city, "forecast": res["forecast"], "basis": res["basis"]}
        except Exception as ex:
            return {"ok": False, "city": city, "error": str(ex)}

    with ThreadPoolExecutor(max_workers=7) as pool:
        rows = list(pool.map(_one, CITIES))
    return jsonify({"ok": True, "days": days, "rows": rows})


@app.route("/api/predict/reliability")
def api_projection_reliability():
    path = os.path.join(DATA_DIR, "projection_test_table.csv")
    if not os.path.isfile(path):
        return jsonify({"available": False, "rows": []})
    try:
        with open(path, newline="", encoding="utf-8-sig") as table_file:
            reader = csv.DictReader(table_file)
            required_columns = {
                "days_ahead", "model_mae", "repeat_today_mae",
                "within_20_pct", "model_p80_error"
            }
            missing_columns = required_columns.difference(reader.fieldnames or [])
            if missing_columns:
                raise ValueError(
                    "Missing columns: " + ", ".join(sorted(missing_columns))
                )
            rows = [
                {
                    "days_ahead": int(row["days_ahead"]),
                    "model_mae": float(row["model_mae"]),
                    "repeat_today_mae": float(row["repeat_today_mae"]),
                    "within_20_pct": float(row["within_20_pct"]),
                    "model_p80_error": float(row["model_p80_error"]),
                }
                for row in reader
            ]
        return jsonify({"available": True, "rows": rows})
    except (OSError, ValueError, csv.Error) as ex:
        return err(f"Could not read projection reliability table: {ex}")


@app.route("/api/predict/direct-metrics")
def api_direct_forecast_metrics():
    path = os.path.join("models", "direct_aqi_metrics.json")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.isfile(path):
        return jsonify({"available": False, "metrics": []})
    try:
        with open(path, encoding="utf-8") as metrics_file:
            metrics = json.load(metrics_file)
        if metrics.get("model_type") != "direct_multi_horizon_xgboost":
            raise ValueError("Unrecognized direct forecast metrics model_type")
        if not isinstance(metrics.get("metrics"), list):
            raise ValueError("Metrics JSON must contain a metrics list")
        return jsonify({"available": True, **metrics})
    except (OSError, ValueError, json.JSONDecodeError) as ex:
        return err(f"Could not read direct forecast metrics: {ex}")


@app.route("/api/compare/today")
def api_compare_today():
    if not data_service.available():
        return err("Historical data not loaded. Run prepare_data.py", 503)
    try:
        res = comparison_service.compare_today()
        res["ok"] = True
        return jsonify(res)
    except Exception as ex:
        return err(ex)


# ------------------------------------------------------------------ API: sources & policy
@app.route("/api/sources/<city>")
def api_sources(city):
    c, e = city_or_404(city)
    if e: return e
    res = source_service.infer(c)
    return jsonify(res), (200 if res.get("ok") else 502)


@app.route("/api/policy/overview")
def api_policy_overview():
    return jsonify(policy_service.overview())


@app.route("/api/policy/districts")
def api_policy_districts():
    return jsonify({"districts": policy_service.districts()})


@app.route("/api/policy/policies/<district>")
def api_policy_policies(district):
    return jsonify({"district": district, "policies": policy_service.policies_for_district(district)})


@app.route("/api/policy/pollutants/<policy>")
def api_policy_pollutants(policy):
    return jsonify({"policy": policy, "pollutants": policy_service.pollutants_for_policy(policy)})


@app.route("/api/policy/analyze", methods=["POST"])
def api_policy_analyze():
    body = request.get_json(silent=True) or {}
    district = body.get("district") or body.get("city")
    policy = body.get("policy")
    months = body.get("window_months") if body.get("window_months") is not None else body.get("window")
    if not district or not policy:
        return err("district and policy are required", 400)
    try:
        return jsonify(policy_service.analyze(district, policy, months or 1))
    except Exception as ex:
        return err(ex, 400)


@app.route("/api/policy/table/<key>")
def api_policy_table(key):
    district = request.args.get("district")
    if district:
        district, e = city_or_404(district)
        if e: return e
    try:
        return jsonify(policy_service.table(key, district, request.args.get("q")))
    except KeyError:
        return err("Unknown table", 404)
    except Exception as ex:
        return err(f"Could not read workbook: {ex}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)),
            debug=os.getenv("FLASK_DEBUG", "0") == "1")
