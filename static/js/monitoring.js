const citySelect = document.getElementById("city");

const aqiValue = document.getElementById("aqi-value");
const aqiCategory = document.getElementById("aqi-category");
const aqiLocation = document.getElementById("aqi-location");

const statusText = document.getElementById("status-text");
const lastUpdated = document.getElementById("last-updated");

const pm25 = document.getElementById("pm25");
const pm10 = document.getElementById("pm10");
const no2 = document.getElementById("no2");
const so2 = document.getElementById("so2");
const co = document.getElementById("co");
const ozone = document.getElementById("ozone");


async function loadMonitoringData(city) {

    try {

        // Show loading state
        aqiValue.textContent = "...";
        aqiCategory.textContent = "Loading data...";
        statusText.textContent = "Loading...";
        lastUpdated.textContent = "Updating...";


        // Request data from Flask
        const response = await fetch(
            `/api/monitoring/${encodeURIComponent(city)}`
        );


        if (!response.ok) {
            throw new Error("Server error");
        }


        const data = await response.json();


        // Check API response
        if (!data.success) {
            throw new Error(data.error || "Unable to get data");
        }


        // -----------------------------
        // AQI
        // -----------------------------

        aqiValue.textContent =
            data.aqi !== null ? data.aqi : "--";

        aqiCategory.textContent =
            data.category || "Unavailable";

        aqiLocation.textContent =
            data.city;


        // -----------------------------
        // AQI STATUS
        // -----------------------------

        statusText.textContent =
            data.category || "Unavailable";


        // -----------------------------
        // POLLUTANTS
        // -----------------------------

        const pollutants = data.pollutants || {};

        pm25.textContent =
            pollutants["PM2.5"] ?? "--";

        pm10.textContent =
            pollutants["PM10"] ?? "--";

        no2.textContent =
            pollutants["NO2"] ?? "--";

        so2.textContent =
            pollutants["SO2"] ?? "--";

        co.textContent =
            pollutants["CO"] ?? "--";

        ozone.textContent =
            pollutants["OZONE"] ?? "--";


        // -----------------------------
        // LAST UPDATED
        // -----------------------------

        lastUpdated.textContent =
            data.updated || "Not available";


    } catch (error) {

        console.error("Monitoring error:", error);

        aqiValue.textContent = "--";

        aqiCategory.textContent =
            "Data unavailable";

        statusText.textContent =
            "Unable to retrieve data";

        lastUpdated.textContent =
            "Connection error";

        pm25.textContent = "--";
        pm10.textContent = "--";
        no2.textContent = "--";
        so2.textContent = "--";
        co.textContent = "--";
        ozone.textContent = "--";
    }
}


// Load Bengaluru when page opens
loadMonitoringData(citySelect.value);


// Load new data whenever city changes
citySelect.addEventListener("change", function () {

    loadMonitoringData(this.value);

});
// ---------------------------------------------
// AQI TREND CHART
// ---------------------------------------------

const chartMessage = document.getElementById("chart-message");

let aqiChart = null;


function createEmptyChart() {

    const canvas = document.getElementById("aqiTrendChart");

    if (!canvas) {
        return;
    }


    const ctx = canvas.getContext("2d");


    aqiChart = new Chart(ctx, {

        type: "line",

        data: {

            labels: [],

            datasets: [{
                label: "AQI",
                data: [],
                tension: 0.3,
                borderWidth: 2,
                pointRadius: 4
            }]

        },

        options: {

            responsive: true,

            maintainAspectRatio: false,

            scales: {

                y: {
                    beginAtZero: true,
                    title: {
                        display: true,
                        text: "AQI"
                    }
                },

                x: {
                    title: {
                        display: true,
                        text: "Date"
                    }
                }

            },

            plugins: {

                legend: {
                    display: true
                }

            }

        }

    });
}


createEmptyChart();