"""Real-time monitoring from the live CPCBCCR API, plus a separate sensor store.

API monitoring, physical sensors and ML prediction are independent data
sources. Sensor readings never replace API pollutant values on monitoring
pages. Successful API fetches are logged so the 48-hour CPCBCCR trend can
be drawn from timestamped records stored by this app."""
import os
import json
import time
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests

from . import aqi_service as aqi
from .data_service import CITY_COORDS, DATA_DIR
from .freshness import source_age_minutes

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.path.join(DATA_DIR, "airwise.db")


def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


class MonitoringService:
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()
        self._init_db()

    # ---- sqlite ------------------------------------------------------------
    def _db(self):
        con = sqlite3.connect(DB_PATH, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with self._db() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS live_log(
                id INTEGER PRIMARY KEY, city TEXT, ts_utc TEXT, api_time TEXT,
                aqi INTEGER, dominant TEXT, pollutants TEXT)""")
            con.execute("""CREATE TABLE IF NOT EXISTS sensor_readings(
                id INTEGER PRIMARY KEY, city TEXT, device_id TEXT, ts_utc TEXT,
                pollutants TEXT)""")
            con.execute("CREATE INDEX IF NOT EXISTS ix_live ON live_log(city, ts_utc)")
            con.execute("CREATE INDEX IF NOT EXISTS ix_sens ON sensor_readings(city, ts_utc)")

    @staticmethod
    def _parse_timestamp(value):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=IST) if parsed.tzinfo is None else parsed.astimezone(IST)

    @staticmethod
    def _display_timestamp(value):
        parsed = MonitoringService._parse_timestamp(value)
        return parsed.strftime("%Y-%m-%d %H:%M:%S IST") if parsed else None

    def _last_success_time(self, city):
        with self._db() as con:
            row = con.execute(
                "SELECT ts_utc FROM live_log WHERE city=? AND ts_utc IS NOT NULL ORDER BY id DESC LIMIT 1",
                (city,),
            ).fetchone()
        return self._display_timestamp(row["ts_utc"]) if row else None

    def last_success_time(self, city):
        return self._last_success_time(city)

    def _feed_failure(self, city, message):
        last_success = self._last_success_time(city)
        return {
            "ok": False,
            "error": f"Estimate unavailable (last success: {last_success or '--'})",
            "detail": message,
            "last_success": last_success,
        }

    # ---- live API ---------------------------------------------------------------
    def fetch_api(self, city):
        """Raw pollutant values from the live API; cached per city."""
        ttl = min(600, max(0, _env_int("CACHE_TTL_SECONDS", 600)))
        with self._lock:
            hit = self._cache.get(city)
            if hit and time.time() - hit["t"] < ttl:
                return hit["data"]
        lat, lon = CITY_COORDS[city]
        url = os.getenv("CPCB_API_URL", "https://app.cpcbccr.com/api/location-data")
        try:
            r = requests.get(url, params={"lat": lat, "lon": lon, "fresh": "1"}, timeout=25)
            if r.status_code != 200:
                return self._feed_failure(city, f"Live API returned HTTP {r.status_code}")
            payload = r.json()
            aq = payload.get("airQuality", {}) or {}
            cur = aq.get("current", {}) or {}
            co_ug = cur.get("carbon_monoxide")
            vals = {
                "PM2.5": cur.get("pm2_5"), "PM10": cur.get("pm10"),
                "NO2": cur.get("nitrogen_dioxide"), "SO2": cur.get("sulphur_dioxide"),
                "CO": (float(co_ug) / 1000.0) if co_ug is not None else None,   # µg/m³ -> mg/m³
                "OZONE": cur.get("ozone"),
            }
            data = {"ok": True, "values": vals, "api_time": cur.get("time"),
                    "us_aqi": cur.get("us_aqi"),
                    "grid_lat": aq.get("latitude"), "grid_lon": aq.get("longitude"),
                    "fetched_at": datetime.now(timezone.utc).isoformat()}
        except Exception as e:  # network, JSON, timeout
            return self._feed_failure(city, f"Live API unreachable: {e}")
        with self._lock:
            self._cache[city] = {"t": time.time(), "data": data}
        self._log_live(city, data)
        return data

    def _log_live(self, city, data):
        try:
            res = aqi.calculate_aqi(data["values"])
            with self._db() as con:
                con.execute("INSERT INTO live_log(city, ts_utc, api_time, aqi, dominant, pollutants) VALUES(?,?,?,?,?,?)",
                            (city, datetime.now(timezone.utc).isoformat(), data.get("api_time"),
                             res["aqi"], res["dominant"], json.dumps(data["values"])))
        except Exception:
            pass

    # ---- sensors -------------------------------------------------------------------
    def ingest_sensor(self, city, device_id, values):
        clean = {}
        for p in aqi.POLLUTANTS:
            v = aqi._num(values.get(p, values.get(p.lower())))
            if v is not None and v >= 0:
                clean[p] = v
        if not clean:
            raise ValueError("No valid pollutant values in payload")
        with self._db() as con:
            con.execute("INSERT INTO sensor_readings(city, device_id, ts_utc, pollutants) VALUES(?,?,?,?)",
                        (city, device_id or "unknown", datetime.now(timezone.utc).isoformat(), json.dumps(clean)))
        with self._lock:
            self._cache.pop(city, None)
        return clean

    def latest_sensor(self, city):
        max_age = _env_int("SENSOR_MAX_AGE_MIN", 60)
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age)).isoformat()
        with self._db() as con:
            rows = con.execute("SELECT * FROM sensor_readings WHERE city=? AND ts_utc>=? ORDER BY ts_utc DESC LIMIT 50",
                               (city, cutoff)).fetchall()
        if not rows:
            return None
        merged, ts, devices = {}, rows[0]["ts_utc"], set()
        for r in rows:                      # newest reading per pollutant wins
            devices.add(r["device_id"])
            for p, v in json.loads(r["pollutants"]).items():
                merged.setdefault(p, v)
        return {"values": merged, "ts_utc": ts, "devices": sorted(devices)}

    def sensor_status(self):
        with self._db() as con:
            n = con.execute("SELECT COUNT(*) c FROM sensor_readings").fetchone()["c"]
            last = con.execute("SELECT city, device_id, ts_utc FROM sensor_readings ORDER BY ts_utc DESC LIMIT 1").fetchone()
        return {"total_readings": n, "last": dict(last) if last else None}

    def _pollutant_cards(self, values, res, source):
        cards = []
        for p in aqi.POLLUTANTS:
            v = values.get(p)
            cards.append({
                "key": p, "label": aqi.LABELS[p],
                "value": None if v is None else round(float(v), 2),
                "unit": aqi.UNITS[p], "subindex": res["subindices"].get(p),
                "source": source, "info": aqi.POLLUTANT_INFO[p],
            })
        return cards

    def current(self, city):
        """CPCBCCR API snapshot only. Physical sensors are not mixed in."""
        api = self.fetch_api(city)
        if not api.get("ok"):
            return {
                "ok": False,
                "city": city,
                "error": api.get("error", "Estimate unavailable (last success: --)"),
                "api_ok": False,
                "api_error": api.get("detail"),
                "last_success": api.get("last_success"),
                "data_sources": ["api"],
            }

        values = {}
        for p in aqi.POLLUTANTS:
            if api["values"].get(p) is not None:
                values[p] = float(api["values"][p])
        res = aqi.calculate_aqi(values)
        cat = aqi.category(res["aqi"])
        now = datetime.now(IST)
        api_timestamp = self._parse_timestamp(api.get("api_time"))
        api_age_minutes = source_age_minutes(api_timestamp, now)
        estimate_time = api_timestamp.strftime("%Y-%m-%d %H:%M:%S IST") if api_timestamp else None
        return {
            "ok": True, "city": city,
            "aqi": res["aqi"], "category": cat, "color": aqi.color(res["aqi"]),
            "dominant": res["dominant"], "dominant_info": aqi.POLLUTANT_INFO.get(res["dominant"]),
            "health": aqi.HEALTH.get(cat),
            "pollutants": self._pollutant_cards(values, res, "api"),
            "missing": [aqi.LABELS[p] for p in aqi.POLLUTANTS if values.get(p) is None],
            "values": values,
            "data_sources": ["api"],
            "api_ok": True, "api_error": None,
            "api_time": api.get("api_time"), "us_aqi": api.get("us_aqi"),
            "estimate_time": estimate_time,
            "estimate_age_minutes": None if api_age_minutes is None else round(api_age_minutes, 1),
            "estimate_old": api_age_minutes is not None and api_age_minutes > 180,
            "source_ages": {
                "cpcbccr": {
                    "timestamp": estimate_time,
                    "age_minutes": api_age_minutes,
                } if api_timestamp else None,
                "sensor": None,
            },
            "feed_warning": None,
            "sensor": None,
            "grid": [api.get("grid_lat"), api.get("grid_lon")],
            "coords": CITY_COORDS[city],
            "fetched_at": self._display_timestamp(api.get("fetched_at")),
        }

    def sensor_current(self, city):
        """Latest hardware-sensor snapshot for a district. Independent of the API."""
        sensor = self.latest_sensor(city)
        if not sensor:
            return {
                "ok": False, "city": city,
                "error": "No recent sensor readings for this district.",
                "data_sources": ["sensor"],
            }
        values = {p: float(sensor["values"][p]) for p in aqi.POLLUTANTS if p in sensor["values"]}
        res = aqi.calculate_aqi(values)
        cat = aqi.category(res["aqi"])
        now = datetime.now(IST)
        sensor_timestamp = self._parse_timestamp(sensor["ts_utc"])
        age_minutes = source_age_minutes(sensor_timestamp, now)
        stamp = sensor_timestamp.strftime("%Y-%m-%d %H:%M:%S IST") if sensor_timestamp else None
        return {
            "ok": True, "city": city,
            "aqi": res["aqi"], "category": cat, "color": aqi.color(res["aqi"]),
            "dominant": res["dominant"], "dominant_info": aqi.POLLUTANT_INFO.get(res["dominant"]),
            "health": aqi.HEALTH.get(cat),
            "pollutants": self._pollutant_cards(values, res, "sensor"),
            "missing": [aqi.LABELS[p] for p in aqi.POLLUTANTS if values.get(p) is None],
            "values": values,
            "data_sources": ["sensor"],
            "devices": sensor["devices"],
            "ts_utc": sensor["ts_utc"],
            "estimate_time": stamp,
            "estimate_age_minutes": None if age_minutes is None else round(age_minutes, 1),
            "estimate_old": age_minutes is not None and age_minutes > 180,
            "source_ages": {
                "cpcbccr": None,
                "sensor": {"timestamp": stamp, "age_minutes": age_minutes} if sensor_timestamp else None,
            },
        }

    def live_log(self, city, hours=48):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with self._db() as con:
            rows = con.execute("SELECT ts_utc, aqi FROM live_log WHERE city=? AND ts_utc>=? AND aqi IS NOT NULL ORDER BY ts_utc",
                               (city, cutoff)).fetchall()
        out = []
        for r in rows:
            t = datetime.fromisoformat(r["ts_utc"]).astimezone(IST)
            out.append({"t": t.strftime("%d %b %H:%M"), "iso": r["ts_utc"], "aqi": r["aqi"]})
        return out

    def sensor_log(self, city, hours=48):
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with self._db() as con:
            rows = con.execute(
                "SELECT device_id, ts_utc, pollutants FROM sensor_readings WHERE city=? AND ts_utc>=? ORDER BY ts_utc",
                (city, cutoff),
            ).fetchall()
        out = []
        for r in rows:
            values = json.loads(r["pollutants"])
            res = aqi.calculate_aqi(values)
            t = datetime.fromisoformat(r["ts_utc"]).astimezone(IST)
            out.append({
                "t": t.strftime("%d %b %H:%M"),
                "iso": r["ts_utc"],
                "device_id": r["device_id"],
                "aqi": res["aqi"],
                "values": values,
            })
        return out

    def export_readings(self, city=None, limit=5000):
        limit = max(1, min(int(limit), 20000))
        sql = "SELECT city, device_id, ts_utc, pollutants FROM sensor_readings"
        args = []
        if city:
            sql += " WHERE city=?"
            args.append(city)
        sql += " ORDER BY ts_utc DESC LIMIT ?"
        args.append(limit)
        with self._db() as con:
            rows = con.execute(sql, args).fetchall()
        readings = []
        for r in reversed(rows):
            payload = {"city": r["city"], "device_id": r["device_id"], "ts_utc": r["ts_utc"]}
            payload.update(json.loads(r["pollutants"]))
            readings.append(payload)
        return {"ok": True, "count": len(readings), "readings": readings}


monitoring_service = MonitoringService()
