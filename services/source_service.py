"""Show elevated pollutant indicators and broad source associations.

The current-hour snapshot cannot identify or apportion emission sources.
"""

from . import aqi_service as aqi
from .data_service import data_service
from .monitoring_service import monitoring_service


# ============================================================
# POLLUTANT SIGNATURES
# ============================================================

SIGNATURES = {

    "PM10": (
        "Possible PM10 contributors",

        "Coarse particles can come from road dust, construction and soil, "
        "among other sources. A pollutant reading alone cannot identify "
        "which source contributed."
    ),

    "PM2.5": (
        "Possible PM2.5 contributors",

        "Fine particles can come from combustion and secondary atmospheric "
        "formation, among other sources. A pollutant reading alone cannot "
        "identify which source contributed."
    ),

    "NO2": (
        "Possible NO2 contributors",

        "NO2 can be associated with traffic and other high-temperature "
        "combustion. A pollutant reading alone cannot identify which source "
        "contributed."
    ),

    "SO2": (
        "Possible SO2 contributors",

        "SO2 can be associated with sulphur-containing fuels and industrial "
        "combustion. A pollutant reading alone cannot identify which source "
        "contributed."
    ),

    "CO": (
        "Possible CO contributors",

        "CO can be associated with incomplete combustion, including traffic "
        "and burning. A pollutant reading alone cannot identify which source "
        "contributed."
    ),

    "OZONE": (
        "Secondary pollutant; sunlight-driven formation",

        "Ground-level ozone forms through atmospheric reactions involving "
        "precursors such as NOx and VOCs in sunlight. An ozone reading does "
        "not identify the precursor source or show that local emissions "
        "caused the observed level."
    )
}


# ============================================================
# MAIN INFERENCE
# ============================================================

def infer(city):

    # --------------------------------------------------------
    # 1. Try live monitoring first
    # --------------------------------------------------------

    current = monitoring_service.current(
        city
    )

    if (
        current.get("ok")
        and current.get("aqi") is not None
    ):

        values = current.get(
            "values",
            {}
        )

        basis = f"CPCBCCR API pollutants ({current.get('estimate_time') or '--'})"
        if current.get("estimate_old"):
            basis = f"Old CPCBCCR API pollutants ({current.get('estimate_time') or '--'})"

    else:

        # ----------------------------------------------------
        # 2. Historical fallback
        # ----------------------------------------------------

        values = (
            data_service.baseline_means(
                city,
                365
            )
            or {}
        )

        values = {
            k: v
            for k, v in values.items()
            if v is not None
        }

        last_date = data_service.data_through(city)
        basis = f"Historical 12-month mean through {last_date.strftime('%Y-%m-%d') if last_date is not None else '--'}"

    if not values:

        return {

            "ok": False,

            "city": city,

            "error":
                "No live or historical data available."
        }


    # --------------------------------------------------------
    # 3. CPCB AQI
    # --------------------------------------------------------

    result = aqi.calculate_aqi(
        values
    )

    if result["aqi"] is None:

        return {

            "ok": False,

            "city": city,

            "error":
                "Not enough valid pollutants "
                "to calculate AQI."
        }


    subs = result[
        "subindices"
    ]


    # --------------------------------------------------------
    # 4. Find elevated pollutant indicators
    # --------------------------------------------------------

    signals = []

    for pollutant, subindex in subs.items():

        if subindex is None:
            continue

        if subindex <= 50:
            continue

        if pollutant not in SIGNATURES:
            continue

        source_name, explanation = (
            SIGNATURES[pollutant]
        )

        evidence = [

            f"{aqi.LABELS[pollutant]} "
            f"sub-index {subindex:.0f} "
            f"(above the CPCB elevated threshold of 50)"
        ]


        signals.append({

            "pollutant":
                pollutant,

            "label":
                aqi.LABELS[pollutant],

            "source":
                source_name,

            "explanation":
                explanation,

            "score":
                subindex,

            "evidence":
                evidence
        })


    # --------------------------------------------------------
    # Highest pollutant signal first
    # --------------------------------------------------------

    signals.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    # --------------------------------------------------------
    # Seasonal AQI information
    # --------------------------------------------------------

    seasonal = (
        data_service.monthly_profile(
            city
        )
    )


    # --------------------------------------------------------
    # Final result
    # --------------------------------------------------------

    return {

        "ok":
            True,

        "city":
            city,

        "basis":
            basis,

        "aqi":
            result["aqi"],

        "category":
            aqi.category(
                result["aqi"]
            ),

        "dominant":
            result["dominant"],

        "signals":
            signals,

        "within_good":
            len(signals) == 0,

        "seasonal":
            seasonal,

        "caveat":
            "Inference uses the same pollutant-to-contributor rules as the Colab notebook: elevated CPCB sub-indices (above 50) are listed with possible sources. This is rule-based association, not source apportionment. API readings, physical sensors and ML forecasts are kept as separate modules."
    }