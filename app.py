from flask import Flask, render_template
from services.waqi_service import get_pollution_data_by_station_id

from services.policy_service import (
    get_districts,
    get_policies_for_district,
    get_policy_pollutants,
    analyze_policy
)
app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/monitoring")
def monitoring():
    return render_template("monitoring.html")


@app.route("/policy")
def policy():
    return render_template("policy.html")


@app.route("/prediction")
def prediction():
    return "Future AQI Prediction - Coming Soon"


@app.route("/api/monitoring/<city>")
def monitoring_api(city):

    data = get_pollution_data_by_station_id(city)

    return data

@app.route("/api/policy/districts")
def policy_districts():

    return {
        "districts": get_districts()
    }
@app.route("/api/policy/policies/<city>")
def policy_policies(city):

    return {
        "policies":
            get_policies_for_district(city)
    }
@app.route("/api/policy/pollutants/<policy>")
def policy_pollutants(policy):

    return {
        "pollutants":
            get_policy_pollutants(policy)
    }
@app.route("/api/policy/analyze", methods=["POST"])
def policy_analyze():

    from flask import request

    data = request.get_json()

    city = data.get("city")
    policy = data.get("policy")
    window = int(data.get("window", 3))

    result = analyze_policy(
        city,
        policy,
        window
    )

    return result
if __name__ == "__main__":
    app.run(debug=True)