import requests


# -------------------------------------------------
# WAQI API TOKEN
# -------------------------------------------------
# IMPORTANT:
# Put your actual WAQI token here temporarily.
# Later we will move it to an environment variable.
TOKEN = "99e20b8412b799bbca76b7e965c87313a55280a6"


# -------------------------------------------------
# CITY → WAQI STATION ID
# Based on your existing project code
# -------------------------------------------------
district_station_ids = {
    "Bagalkot": "@14154",
    "Belgaum": "@14155",
    "Bengaluru": "@8190",
    "Chamarajanagar": "@14157",
    "Chikkaballapur": "@14158",
    "Chikkamagaluru": "@14159",
    
    "Dharwad": "@14161",
    "Hubballi": "@14162",
    "Kalaburagi": "@14163",
    "Madikeri": "@14164",
    "Mangalore": "@14165",
    "Mysuru": "@14166",
    "Ramanagara": "@14167",
    "Tumakuru": "@14168",
    "Yadgir": "@14169"
}


# -------------------------------------------------
# AQI CATEGORIES
# -------------------------------------------------
def get_aqi_category(aqi):

    if aqi is None:
        return "Unavailable"

    if aqi <= 50:
        return "Good"
    elif aqi <= 100:
        return "Satisfactory"
    elif aqi <= 200:
        return "Moderate"
    elif aqi <= 300:
        return "Poor"
    elif aqi <= 400:
        return "Very Poor"
    else:
        return "Severe"


# -------------------------------------------------
# FETCH LIVE DATA
# -------------------------------------------------
def get_pollution_data_by_station_id(selected_city):

    expected_pollutants = {
        "CO",
        "SO2",
        "PM2.5",
        "PM10",
        "OZONE",
        "NO2"
    }

    station_uid = district_station_ids.get(selected_city)

    if not station_uid:
        return {
            "success": False,
            "error": "City not found"
        }

    try:

        url = (
            f"https://api.waqi.info/feed/"
            f"{station_uid}/?token={TOKEN}"
        )

        response = requests.get(url, timeout=10)

        response.raise_for_status()

        data = response.json()

    except requests.RequestException as e:

        return {
            "success": False,
            "error": f"API connection error: {str(e)}"
        }

    except ValueError:

        return {
            "success": False,
            "error": "Invalid API response"
        }


    # -------------------------------------------------
    # CHECK WAQI RESPONSE
    # -------------------------------------------------

    if data.get("status") != "ok":

        return {
            "success": False,
            "error": data.get(
                "data",
                "Unable to retrieve air quality data"
            )
        }


    api_data = data.get("data", {})

    iaqi = api_data.get("iaqi", {})

    pollutants = {}


    # -------------------------------------------------
    # EXTRACT POLLUTANTS
    # -------------------------------------------------

    for key, value_obj in iaqi.items():

        standardized_key = key.upper()

        # WAQI uses pm25
        if standardized_key == "PM25":
            standardized_key = "PM2.5"

        # WAQI uses o3
        elif standardized_key == "O3":
            standardized_key = "OZONE"

        if standardized_key in expected_pollutants:

            try:
                pollutants[standardized_key] = float(
                    value_obj["v"]
                )

            except (ValueError, KeyError, TypeError):
                continue


    # -------------------------------------------------
    # AQI
    # -------------------------------------------------

    # WAQI provides its own AQI value.
    # We use it for real-time monitoring.
    aqi = api_data.get("aqi")

    try:
        aqi = int(float(aqi))
    except (ValueError, TypeError):
        aqi = None


    category = get_aqi_category(aqi)


    # -------------------------------------------------
    # LAST UPDATED
    # -------------------------------------------------

    time_data = api_data.get("time", {})

    updated_time = time_data.get(
        "s",
        "Not available"
    )


    return {

        "success": True,

        "city": selected_city,

        "aqi": aqi,

        "category": category,

        "pollutants": {

            "PM2.5": pollutants.get("PM2.5"),

            "PM10": pollutants.get("PM10"),

            "NO2": pollutants.get("NO2"),

            "SO2": pollutants.get("SO2"),

            "CO": pollutants.get("CO"),

            "OZONE": pollutants.get("OZONE")

        },

        "updated": updated_time

    }