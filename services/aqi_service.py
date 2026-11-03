"""CPCB AQI maths. Single source of truth used by every other service."""
import math

POLLUTANTS = ["PM2.5", "PM10", "NO2", "SO2", "CO", "OZONE"]

UNITS = {"PM2.5": "µg/m³", "PM10": "µg/m³", "NO2": "µg/m³",
         "SO2": "µg/m³", "CO": "mg/m³", "OZONE": "µg/m³"}

LABELS = {"PM2.5": "PM2.5", "PM10": "PM10", "NO2": "NO₂",
          "SO2": "SO₂", "CO": "CO", "OZONE": "Ozone"}

BREAKPOINTS = {
    "PM2.5": [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200),
              (91, 120, 201, 300), (121, 250, 301, 400), (251, 500, 401, 500)],
    "PM10": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 250, 101, 200),
             (251, 350, 201, 300), (351, 430, 301, 400), (431, 1000, 401, 500)],
    "NO2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 180, 101, 200),
            (181, 280, 201, 300), (281, 400, 301, 400), (401, 1000, 401, 500)],
    "SO2": [(0, 40, 0, 50), (41, 80, 51, 100), (81, 380, 101, 200),
            (381, 800, 201, 300), (801, 1600, 301, 400), (1601, 2000, 401, 500)],
    "CO": [(0, 1, 0, 50), (1.1, 2, 51, 100), (2.1, 10, 101, 200),
           (10.1, 17, 201, 300), (17.1, 34, 301, 400), (34.1, 50, 401, 500)],
    "OZONE": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 168, 101, 200),
              (169, 208, 201, 300), (209, 748, 301, 400), (749, 1000, 401, 500)],
}

# Wording from the notebook (pollutant_causes_data)
POLLUTANT_INFO = {
    "PM2.5": "Fine particles can penetrate deep into the lungs and may affect respiratory health.",
    "PM10": "Coarse particles can irritate the eyes, nose and respiratory system.",
    "NO2": "Nitrogen dioxide can irritate the respiratory system and is associated with traffic and combustion emissions.",
    "SO2": "Sulphur dioxide can irritate the airways and is commonly associated with combustion of sulphur-containing fuels.",
    "CO": "Carbon monoxide reduces the blood's ability to carry oxygen and is produced mainly by incomplete combustion.",
    "OZONE": "Ground-level ozone can irritate the respiratory system and is formed through atmospheric chemical reactions.",
}

# CPCB National AQI health statements
HEALTH = {
    "Good": "Minimal impact.",
    "Satisfactory": "May cause minor breathing discomfort to sensitive people.",
    "Moderate": "May cause breathing discomfort to people with lung disease such as asthma, and discomfort to people with heart disease, children and older adults.",
    "Poor": "May cause breathing discomfort to most people on prolonged exposure, and discomfort to people with heart disease.",
    "Very Poor": "May cause respiratory illness on prolonged exposure.",
    "Severe": "May cause respiratory impact even on healthy people, and serious health impacts on people with lung/heart disease.",
}

ALIASES = {"O3": "OZONE", "Ozone": "OZONE", "ozone": "OZONE"}


def _num(v):
    try:
        if v is None:
            return None
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def subindex(value, pollutant):
    pollutant = ALIASES.get(pollutant, pollutant)
    v = _num(value)
    if v is None or v < 0:
        return None
    bps = BREAKPOINTS[pollutant]
    for index, (lo, hi, ilo, ihi) in enumerate(bps):
        if lo <= v <= hi:
            return round((ihi - ilo) / (hi - lo) * (v - lo) + ilo, 2)
        if index + 1 < len(bps):
            next_lo, _, next_ilo, _ = bps[index + 1]
            if hi < v < next_lo:
                return float(next_ilo)
    return 500.0 if v > bps[-1][1] else None


def subindex_for_display(value, pollutant):
    """Return a rounded display value while preserving the original underlying concentration for AQI math."""
    return round(subindex(value, pollutant), 2) if subindex(value, pollutant) is not None else None


def calculate_aqi(values):
    """values: {pollutant: concentration}. CPCB rule (as in the notebook's
    historical AQI): at least 3 pollutants, one of them PM2.5 or PM10.
    Returns dict(aqi, dominant, subindices, valid_count)."""
    subs = {p: subindex(values.get(p), p) for p in POLLUTANTS}
    valid = {k: v for k, v in subs.items() if v is not None}
    has_pm = subs.get("PM2.5") is not None or subs.get("PM10") is not None
    if len(valid) < 3 or not has_pm:
        return {"aqi": None, "dominant": None, "subindices": subs, "valid_count": len(valid)}
    dom = max(valid, key=valid.get)
    return {"aqi": int(round(valid[dom])), "dominant": dom,
            "subindices": subs, "valid_count": len(valid)}


def category(aqi):
    a = _num(aqi)
    if a is None: return "Unavailable"
    if a <= 50: return "Good"
    if a <= 100: return "Satisfactory"
    if a <= 200: return "Moderate"
    if a <= 300: return "Poor"
    if a <= 400: return "Very Poor"
    return "Severe"


def color(aqi):
    a = _num(aqi)
    if a is None: return "#808080"
    if a <= 50: return "#00A651"
    if a <= 100: return "#A3D977"
    if a <= 200: return "#FFF200"
    if a <= 300: return "#F7941D"
    if a <= 400: return "#ED1C24"
    return "#7E0023"
