/* AIRWISE front-end. Every number shown comes from the Flask API. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const chip = (cat, color) => `<span class="chip" style="background:${color};color:${String(color).toUpperCase() === "#7E0023" ? "#ffffff" : "#111827"}">${esc(cat)}</span>`;
const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v)) ? "--" : Number(v).toFixed(d);

async function api(url, opts = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...opts, signal: controller.signal });
    let j = null;
    try { j = await r.json(); } catch (e) { /* non-JSON */ }
    if (!r.ok || (j && j.ok === false)) throw new Error((j && j.error) || `Request failed (${r.status})`);
    return j;
  } catch (e) {
    if (e.name === "AbortError") throw new Error("Data unavailable, retry");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}
const alertBox = (el, kind, msg) => { el.innerHTML = msg ? `<div class="alert ${kind}">${esc(msg)}</div>` : ""; };
const setText = (id, value) => {
  const els = [document.getElementById(id), document.getElementById(id.replace("home", "hero"))];
  els.filter(Boolean).forEach(el => { el.textContent = value; });
};
const charts = {};
function draw(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart($("#" + id), cfg); }
const AQI_COLORS = a => a <= 50 ? "#00A651" : a <= 100 ? "#A3D977" : a <= 200 ? "#FFF200" : a <= 300 ? "#F7941D" : a <= 400 ? "#ED1C24" : "#7E0023";
Chart.defaults.color = "#3d5468";
Chart.defaults.borderColor = "rgba(148,163,184,.12)";
Chart.defaults.font.family = "'DM Sans', sans-serif";

function aqiCategoryBand(value) {
  if (value <= 50) return "Good (0–50)";
  if (value <= 100) return "Satisfactory (51–100)";
  if (value <= 200) return "Moderate (101–200)";
  if (value <= 300) return "Poor (201–300)";
  if (value <= 400) return "Very Poor (301–400)";
  return "Severe (401+)";
}

function categoryBadge(value, category) {
  const background = AQI_COLORS(value);
  const foreground = value > 400 ? "#ffffff" : "#000000";
  return `<span class="chip" style="background:${background};color:${foreground}">${esc(category || aqiCategoryBand(value).split(" (")[0])}</span>`;
}

let monitoringLiveAges = null;
let monitoringStationAge = null;

function formatDataAge(ageMinutes) {
  if (ageMinutes === null || ageMinutes === undefined || !Number.isFinite(Number(ageMinutes))) return "unavailable";
  const minutes = Math.floor(Number(ageMinutes));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (hours < 24) return remainder ? `${hours} h ${remainder} min` : `${hours} h`;
  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return remainingHours ? `${days} d ${remainingHours} h` : `${days} d`;
}

function updateMonitoringAgeWarning() {
  const warnings = [];
  if (monitoringLiveAges) {
    for (const [source, data] of Object.entries(monitoringLiveAges)) {
      if (data && data.age_minutes > 180) {
        const label = source === "cpcbccr" ? "CPCBCCR live data" : "AIRWISE sensor data";
        warnings.push(`${label} is ${formatDataAge(data.age_minutes)} old (over 3 hours).`);
      }
    }
  }
  alertBox($("#dataAgeWarning"), "warn", warnings.join(" "));
}

/* ------------------------------------------------------------ HOME */
async function initHome() {
  const map = L.map("map", { scrollWheelZoom: false, zoomControl: false }).setView([14.8, 76.0], 7);
  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors",
    maxZoom: 19,
    subdomains: "abc"
  }).addTo(map);
  const markerLayer = L.featureGroup().addTo(map);
  let coords = {};
  let cityCount = 0;
  let currentCity = $("#homeCitySelect").value || "Bengaluru";
  let rankingRows = [];

  function renderRanking(rows) {
    rankingRows = rows;
    const rankCount = $("#rankCount");
    const rankTable = $("#rankTable");
    if (rankCount) rankCount.textContent = `${rows.length} / ${cityCount || "--"}`;
    if (rankTable && rankTable.tBodies[0]) rankTable.tBodies[0].innerHTML = rows.map((x, i) =>
      `<tr><td><span class="rank-index">${String(i + 1).padStart(2, "0")}</span><a href="/monitoring?city=${encodeURIComponent(x.city)}">${esc(x.city)}</a></td><td><b>${x.aqi}</b></td><td><span class="rank-status-dot" style="--rank-color:${x.color}"></span>${categoryBadge(x.aqi, x.category)}</td></tr>`).join("");
    markerLayer.clearLayers();
    rows.forEach(x => {
      if (!coords[x.city]) return;
      const marker = L.circleMarker(coords[x.city], {
        radius: 9, color: x.color, fillColor: x.color, fillOpacity: .92, weight: 2,
        className: "aqi-map-marker"
      }).bindTooltip(`<strong>${esc(x.city)}</strong><br>Model estimate (${esc(x.estimate_time || "--")}): AQI ${x.aqi}${x.estimate_old ? " · old estimate" : ""} · ${esc(x.category)}`, { className: "airwise-tooltip" });
      marker.on("click", () => { window.location.href = `/monitoring?city=${encodeURIComponent(x.city)}`; });
      marker.addTo(markerLayer);
    });
    if (markerLayer.getLayers().length) {
      map.fitBounds(markerLayer.getBounds(), { padding: [16, 16], maxZoom: 8 });
    }
  }

  async function loadHomeCity(city) {
    currentCity = city;
    const homeCitySelect = $("#homeCitySelect");
    const heroCityLabel = $("#heroCityLabel");
    const trendCityLabel = $("#trendCityLabel");
    const homeAqi = $("#homeAqi");
    const heroAqi = $("#heroAqi");
    const heroMeter = $("#heroMeter");
    const homeAqiRing = $("#homeAqiRing");
    const homeCategory = $("#homeCategory");
    const homeHealth = $("#homeHealth");
    const heroCategory = $("#heroCategory");
    const heroUpdated = $("#heroUpdated");
    const homeLiveMeta = $("#homeLiveMeta");

    if (homeCitySelect) homeCitySelect.value = city;
    if (heroCityLabel) heroCityLabel.textContent = city;
    if (trendCityLabel) trendCityLabel.textContent = city;
    if (homeAqi) homeAqi.textContent = "--";
    if (heroAqi) heroAqi.textContent = "--";
    if (heroMeter) {
      heroMeter.style.width = "0%";
      heroMeter.style.background = "transparent";
    }
    if (homeAqiRing) {
      homeAqiRing.style.setProperty("--aqi-progress", "0%");
      homeAqiRing.style.setProperty("--aqi-color", "transparent");
    }
    if (homeCategory) homeCategory.textContent = "Connecting…";
    if (homeHealth) homeHealth.textContent = "Loading the latest district estimate…";
    if (heroCategory) heroCategory.textContent = "Connecting…";
    if (heroUpdated) heroUpdated.textContent = "--";
    if (homeLiveMeta) homeLiveMeta.textContent = "API-derived AQI estimate (time): --";
    for (const id of ["homePm25", "homePm10", "homeNo2", "homeSo2", "homeCo", "homeOzone", "heroPm25", "heroPm10", "heroNo2", "heroOzone"]) {
      const el = document.getElementById(id);
      if (el) el.textContent = "--";
    }
    const forecastTitle = $("#homeForecastTitle");
    const forecastAqi = $("#homeForecastAqi");
    if (forecastTitle) forecastTitle.textContent = `${city} projection`;
    if (forecastAqi) forecastAqi.textContent = "--";
    if (charts.homeForecastChart) {
      charts.homeForecastChart.destroy();
      delete charts.homeForecastChart;
    }
    if (charts.homeTrendChart) {
      charts.homeTrendChart.destroy();
      delete charts.homeTrendChart;
    }
    $("#homeTrendTitle").textContent = "CPCBCCR AQI, last 48 hours";
    $("#homeTrendNote").textContent = "Collecting data - 0 record(s) so far";
    try {
      const d = await api(`/api/realtime/${encodeURIComponent(city)}`);
      if (city !== currentCity) return;
      const aqiValue = d.aqi;
      $("#heroAqi").textContent = d.aqi ?? "--";
      $("#heroCategory").innerHTML = d.aqi == null
        ? esc(d.category || "Estimate unavailable")
        : categoryBadge(d.aqi, d.category);
      $("#heroMeter").style.width = aqiValue == null ? "0%" : `${Math.min(aqiValue, 500) / 5}%`;
      $("#heroMeter").style.background = aqiValue == null ? "transparent" : (d.color || AQI_COLORS(aqiValue));
      $("#heroUpdated").textContent = d.estimate_time || "--";
      $("#homeAqi").textContent = d.aqi ?? "--";
      $("#homeCategory").innerHTML = d.aqi == null
        ? esc(d.category || "Unavailable")
        : categoryBadge(d.aqi, d.category);
      $("#homeAqiRing").style.setProperty("--aqi-progress", aqiValue == null ? "0%" : `${Math.min(aqiValue, 500) * .152}%`);
      $("#homeAqiRing").style.setProperty("--aqi-color", aqiValue == null ? "transparent" : (d.color || AQI_COLORS(aqiValue)));
      $("#homeHealth").textContent = d.health || "Not enough current data to provide health context.";
      $("#homeLiveMeta").textContent = `CPCBCCR API ${d.estimate_time ? `(${d.estimate_time})` : "(--)"}${d.estimate_old ? " · old estimate" : ""}${d.feed_warning ? ` · ${d.feed_warning}` : ""}`;
      const values = Object.fromEntries(d.pollutants.map(p => [p.key, p.value]));
      const pollutantMap = {
        "PM2.5": ["homePm25", "heroPm25"],
        PM10: ["homePm10", "heroPm10"],
        NO2: ["homeNo2", "heroNo2"],
        SO2: ["homeSo2"],
        CO: ["homeCo"],
        OZONE: ["homeOzone", "heroOzone"]
      };
      Object.entries(pollutantMap).forEach(([key, ids]) => {
        const value = values[key];
        ids.forEach(id => {
          const el = document.getElementById(id);
          if (el) el.textContent = fmt(value, key === "CO" ? 2 : 1);
        });
      });
      const homeRecommendation = $("#homeRecommendation");
      const homePolicyRecommendation = $("#homePolicyRecommendation");
      if (homeRecommendation) homeRecommendation.textContent = d.health || "Follow local public-health guidance; a usable live health advisory is not available for this reading.";
      if (homePolicyRecommendation) homePolicyRecommendation.textContent = d.dominant
        ? `${d.dominant} currently has the largest calculated pollutant sub-index. Review its indicator alongside historical context before prioritizing action.`
        : "Review local pollutant indicators and historical policy analysis before prioritizing interventions.";
    } catch (e) {
      if (city !== currentCity) return;
      $("#heroCategory").textContent = "Data unavailable, retry";
      $("#heroUpdated").textContent = "Feed unavailable";
      $("#homeCategory").textContent = "Data unavailable, retry";
      $("#homeHealth").textContent = "Data unavailable, retry";
      $("#homeLiveMeta").textContent = "Data unavailable, retry";
      const homeRecommendation = $("#homeRecommendation");
      if (homeRecommendation) homeRecommendation.textContent = "Current health guidance is unavailable because the district feed could not be reached.";
    }

    try {
      const l = await api(`/api/live-log/${encodeURIComponent(city)}?hours=48`);
      if (city !== currentCity) return;
      const points = l.points || [];
      draw("homeTrendChart", {
        type: "line",
        data: { labels: points.map(p => p.t), datasets: [{
          label: "CPCBCCR AQI", data: points.map(p => p.aqi), borderColor: "#38bdf8", backgroundColor: "rgba(56,189,248,.1)",
          fill: true, pointRadius: points.length > 40 ? 0 : 2, pointHitRadius: 10, borderWidth: 2, tension: .38
        }] },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { displayColors: false } },
          scales: {
            x: { grid: { display: false }, ticks: { maxTicksLimit: 6, maxRotation: 0 } },
            y: { beginAtZero: true, grid: { color: "rgba(148,163,184,.1)" }, ticks: { maxTicksLimit: 5 } }
          }
        }
      });
      $("#homeTrendNote").textContent = points.length
        ? `${points.length} API records stored by AIRWISE in the last 48 hours.`
        : "Collecting data - 0 record(s) so far";
      $("#homeTrendTitle").textContent = "CPCBCCR AQI, last 48 hours";
    } catch (e) {
      $("#homeTrendNote").textContent = e.message;
    }

    try {
      const forecastTitle = $("#homeForecastTitle");
      const forecastAqi = $("#homeForecastAqi");
      const forecastCategory = $("#homeForecastCategory");
      const forecastNote = $("#homeForecastNote");
      const forecastChart = $("#homeForecastChart");
      const f = await api(`/api/predict/forecast/${encodeURIComponent(city)}?days=7`);
      if (city !== currentCity || !f.forecast.length) return;
      const points = f.forecast.filter(x => x.value_type === "Persistence outlook");
      if (!points.length) return;
      const first = points[0];
      if (forecastTitle) forecastTitle.textContent = `${city} · Persistence outlook · ${first.date}`;
      if (forecastAqi) forecastAqi.textContent = Math.round(first.aqi);
      if (forecastCategory) {
        forecastCategory.textContent = first.category;
        forecastCategory.style.color = first.color || "";
      }
      if (forecastChart) draw("homeForecastChart", {
        type: "line",
        data: { labels: points.map(x => x.date), datasets: [{
          label: "Projected AQI", data: points.map(x => x.aqi), borderColor: "#34d399",
          backgroundColor: "rgba(52,211,153,.09)", fill: true, pointRadius: 3,
          pointBackgroundColor: "#34d399", borderWidth: 2, tension: .35
        }] },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { displayColors: false } },
          scales: {
            x: { grid: { display: false } },
            y: { beginAtZero: false, grid: { color: "rgba(148,163,184,.1)" }, ticks: { maxTicksLimit: 4 } }
          }
        }
      });
      if (forecastNote) forecastNote.textContent = `Persistence outlook · not measured. ${f.basis.gap_filled_days} preceding gap day(s) were filled for continuity. ${f.basis.assumption} Explore Predictions for the full model basis and validation context.`;
    } catch (e) {
      const forecastNote = $("#homeForecastNote");
      if (forecastNote) forecastNote.textContent = e.message.startsWith("Projection unavailable:")
        ? e.message
        : `Projection unavailable: ${e.message}`;
      if (charts.homeForecastChart) {
        charts.homeForecastChart.destroy();
        delete charts.homeForecastChart;
      }
    }
  }

  try {
    const cities = await api("/api/cities");
    cityCount = cities.length;
    $("#districtCount").textContent = cityCount;
    $("#coverageCount").innerHTML = `${cityCount} <small>districts</small>`;
    coords = Object.fromEntries(cities.map(c => [c.name, [c.lat, c.lon]]));
    $("#homeCitySelect").addEventListener("change", event => loadHomeCity(event.target.value));
  } catch (e) {
    $("#rankStatus").textContent = `District locations are unavailable: ${e.message}`;
  }

  try {
    const r = await api("/api/ranking");
    renderRanking(r.rows);
    const rankStatus = $("#rankStatus");
    const oldEstimates = r.rows.filter(row => row.estimate_old).length;
    if (rankStatus) rankStatus.textContent = `Model estimates available for ${r.rows.length} districts · Old estimates: ${oldEstimates}${r.unavailable.length ? ` · Unavailable: ${r.unavailable.join(", ")}` : ""}`;
  } catch (e) {
    const rankStatus = $("#rankStatus");
    if (rankStatus) rankStatus.textContent = `District ranking unavailable: ${e.message}`;
  }

  try {
    const health = await api("/api/health");
    const totalDays = Object.values(health.history || {}).reduce((sum, district) => sum + (district ? district.days : 0), 0);
    const impactHistory = $("#impactHistory");
    if (impactHistory) impactHistory.textContent = totalDays ? totalDays.toLocaleString() : "—";
  } catch (e) {
    const impactHistory = $("#impactHistory");
    if (impactHistory) impactHistory.textContent = "—";
  }
  loadHomeCity(currentCity);
}

/* ------------------------------------------------------------ MONITORING */
async function loadMonitoring() {
  const city = $("#citySelect").value;
  history.replaceState(null, "", `?city=${encodeURIComponent(city)}`);
  $("#aqiValue").textContent = "--"; $("#aqiCategory").textContent = "Loading…"; $("#pollutantGrid").innerHTML = "";
  $("#aqiBar").innerHTML = "";
  $("#healthText").textContent = "";
  $("#stationAqiValue").textContent = "--";
  $("#stationAqiCategory").textContent = "Loading station data…";
  $("#stationDataAge").textContent = "Data age: --";
  $("#stationOutlierNote").textContent = "";
  $("#stationPollutantsTitle").textContent = "Measured station pollutants";
  $("#stationPollutants").innerHTML = "";
  $("#estimateFreshness").textContent = "Data age: --";
  $("#aqiSourceLabel").textContent = "CPCBCCR API estimate";
  $("#metaText").textContent = "";
  monitoringLiveAges = null;
  monitoringStationAge = null;
  updateMonitoringAgeWarning();
  alertBox($("#alertBox"), "", "");
  try {
    const d = await api(`/api/realtime/${encodeURIComponent(city)}`);
    $("#aqiValue").textContent = d.aqi ?? "--";
    $("#aqiValue").style.color = d.aqi != null ? (d.aqi > 200 ? d.color : "") : "";
    $("#aqiCategory").innerHTML = d.aqi == null
      ? esc(d.category || "Unavailable")
      : categoryBadge(d.aqi, d.category);
    $("#aqiBar").innerHTML = d.aqi != null ? `<i style="left:${Math.min(d.aqi, 500) / 5}%"></i>` : "";
    $("#healthText").textContent = d.health || "";
    const sourceLabels = { api: "CPCBCCR API estimate", sensor: "AIRWISE sensors" };
    const sources = (d.data_sources || []).map(source => sourceLabels[source] || source);
    $("#aqiSourceLabel").textContent = sources.length ? sources.join(" + ") : "Live estimate";
    monitoringLiveAges = {};
    const ageLabels = { cpcbccr: "CPCBCCR", sensor: "AIRWISE sensor" };
    for (const [source, data] of Object.entries(d.source_ages || {})) {
      if (data) monitoringLiveAges[source] = data;
    }
    const contributingSources = (d.data_sources || []).map(source => source === "api" ? "cpcbccr" : source);
    const ageText = contributingSources.map(source => {
      const data = monitoringLiveAges[source];
      return data
        ? `${ageLabels[source] || source}: ${formatDataAge(data.age_minutes)} · ${data.timestamp}`
        : `${ageLabels[source] || source}: source timestamp unavailable`;
    });
    $("#estimateFreshness").textContent = `Data age: ${ageText.join(" | ") || "source timestamp unavailable"}`;
    updateMonitoringAgeWarning();
    $("#metaText").textContent = `Source: ${sources.join(" + ") || "Unavailable"}${d.feed_warning ? ` · ${d.feed_warning}` : ""}`;
    $("#pollutantGrid").innerHTML = d.pollutants.map(p => `
      <div class="pcard ${p.key === d.dominant ? "dom" : ""}" title="${esc(p.info)}">
        <div class="name">${esc(p.label)}</div>
        <div class="val">${p.value === null ? "--" : fmt(p.value, p.key === "CO" ? 2 : p.value < 10 ? 1 : 0)}</div>
        <div class="unit">${esc(p.unit)}</div>
        <div class="sub">${p.subindex === null ? "no data" : "sub-index " + fmt(p.subindex, 2)}</div>
        ${p.source ? `<span class="tag ${p.source}">${p.source === "api" ? "API" : p.source === "sensor" ? "Sensor" : esc(p.source)}</span>` : ""}
      </div>`).join("");
    $("#dominantText").textContent = d.dominant ? `${d.dominant}: ${d.dominant_info}` : "AQI could not be computed (needs at least 3 pollutants including PM2.5 or PM10).";
    const warn = [];
    if (!d.api_ok) warn.push(d.feed_warning || "Estimate unavailable (last success: --)");
    if (d.missing.length) warn.push(`Not reported by the source right now: ${d.missing.join(", ")}. The current-hour AQI estimate uses the pollutants that are available.`);
    if (warn.length) alertBox($("#alertBox"), "warn", warn.join(" "));
  } catch (e) {
    $("#aqiValue").textContent = "--";
    $("#aqiCategory").textContent = "Unavailable";
    $("#healthText").textContent = "";
    $("#dominantText").textContent = "--";
    $("#estimateFreshness").textContent = "Data age: source timestamp unavailable";
    alertBox($("#alertBox"), "err", e.message);
  }
  loadHistoryCharts(city);
}

async function loadHistoryCharts(city) {
  try {
    const h = await api(`/api/history/${encodeURIComponent(city)}?days=90`);
    const station = h.latest_station;
    if (station) {
      $("#stationAqiValue").textContent = station.aqi;
      $("#stationAqiValue").style.color = AQI_COLORS(station.aqi);
      $("#stationAqiCategory").innerHTML = categoryBadge(station.aqi, station.category);
      const stationAgeText = station.age_minutes != null ? formatDataAge(station.age_minutes) : "unavailable";
      $("#stationDataAge").textContent = station.age_minutes != null
        ? `Historical station record: ${stationAgeText} old · source timestamp ${station.source_time || "unavailable"}`
        : "Historical station record: unavailable";
      $("#stationOutlierNote").textContent = station.possible_outlier
        ? "Possible outlier (shown, not removed)." : "";
      monitoringStationAge = station.age_minutes;
    } else {
      $("#stationAqiValue").textContent = "--";
      $("#stationAqiValue").style.color = "";
      $("#stationAqiCategory").textContent = "No measured station AQI available";
      $("#stationDataAge").textContent = "Historical station record: unavailable";
      monitoringStationAge = null;
    }
    updateMonitoringAgeWarning();
    const stationPollutants = $("#stationPollutants");
    if (stationPollutants) stationPollutants.innerHTML = station
      ? station.pollutants.map(p => `
        <div class="pcard">
          <div class="name">${esc(p.label)}</div>
          <div class="val">${p.filled_in ? "--" : fmt(p.value, 1)}</div>
          <div class="unit">${esc(p.unit)}</div>
          ${p.filled_in ? '<span class="tag">filled-in for model use only</span>' : '<span class="tag">Measured station</span>'}
        </div>`).join("")
      : "";
    const stationPollutantsTitle = $("#stationPollutantsTitle");
    if (stationPollutantsTitle && station) {
      stationPollutantsTitle.textContent = `Measured station pollutants (${station.date}, daily record)`;
    }
  } catch (e) {
    $("#stationAqiValue").textContent = "--";
    $("#stationAqiValue").style.color = "";
    $("#stationAqiCategory").textContent = `Station history unavailable: ${e.message}`;
    $("#stationDataAge").textContent = "Data age: unavailable";
    monitoringStationAge = null;
    updateMonitoringAgeWarning();
    $("#stationPollutants").innerHTML = "";
  }
  try {
    const l = await api(`/api/live-log/${encodeURIComponent(city)}?hours=48`);
    if ($("#liveChart")) {
      draw("liveChart", { type: "line", data: { labels: l.points.map(p => p.t), datasets: [{ label: "AQI", data: l.points.map(p => p.aqi), borderColor: "#059669", tension: .2 }] },
        options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 6 } } } } });
    }
    $("#liveNote").textContent = l.points.length ? `${l.points.length} readings recorded.` : "Nothing recorded yet – this fills as the site is used.";
  } catch (e) { $("#liveNote").textContent = e.message; }
}

function initMonitoring() {
  const q = new URLSearchParams(location.search).get("city");
  if (q) $("#citySelect").value = q;
  $("#citySelect").addEventListener("change", loadMonitoring);
  $("#refreshBtn")?.addEventListener("click", loadMonitoring);
  loadMonitoring();
  setInterval(loadMonitoring, 10 * 60 * 1000);
}

/* ------------------------------------------------------------ PREDICTION */
async function runForecast() {
  const city = $("#citySelect").value, days = $("#daysSelect").value, btn = $("#forecastBtn");
  btn.disabled = true; btn.textContent = "Building outlook…";
  $("#forecastCard").hidden = true;
  alertBox($("#forecastError"), "", ""); $("#basisBox").innerHTML = "";
  try {
    const d = await api(`/api/predict/forecast/${encodeURIComponent(city)}?days=${days}`);
    if (!d.forecast.length) throw new Error("No forecast dates are available.");
    $("#forecastCard").hidden = false;
    $("#forecastTable tbody").innerHTML = d.forecast.map(x => {
      return `<tr><td>${esc(x.date)}</td><td>${esc(x.day)}</td><td><b>${x.aqi}</b></td><td>${categoryBadge(x.aqi, x.category || aqiCategoryBand(x.aqi).split(" (")[0])}</td></tr>`;
    }).join("");
    const b = d.basis;
    const fallbackWarning = b.historical_fallback_used ? `<div class="alert warn">Day 1 uses live CPCBCCR pollutants from ${esc(b.input_reference_date || b.history_ends || "--")}; recursive projection after that. Historical station data ends ${esc(b.history_ends || "--")}.</div>` : "";
    $("#basisBox").innerHTML = `<div class="alert info">Day 1 uses live CPCBCCR pollutants from ${esc(b.input_reference_date || b.history_ends || "--")}; recursive projection after that. Historical station data ends ${esc(b.history_ends || "--")}.</div>${fallbackWarning}`;
    $("#modelNote").textContent = b.historical_fallback_used ? (b.historical_fallback_warning || b.assumption) : b.assumption;
    draw("forecastTrendChart", {
      type: "line",
      data: { labels: d.forecast.map(x => x.date), datasets: [{
        label: "Predicted AQI", data: d.forecast.map(x => x.aqi),
        borderColor: "#059669", backgroundColor: "rgba(5,150,105,.12)",
        fill: true, tension: .25, pointRadius: 4
      }] },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
    });
  } catch (e) { alertBox($("#forecastError"), "err", e.message); }
  btn.disabled = false; btn.textContent = "Generate forecast";
}

async function runCompare() {
  const btn = $("#compareBtn");
  const table = $("#compareTable");
  const summary = $("#compareSummary");
  if (!btn && !table && !summary) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Fetching district data…";
  }
  try {
    const d = await api("/api/compare/today");
    const rows = d.rows;
    if (table) {
      table.hidden = false;
      table.tBodies[0].innerHTML = rows.map(r => r.ok
        ? `<tr><td>${esc(r.city)}${r.imputed.length ? ` <span class="tag" title="Missing current pollutants filled from history: ${esc(r.imputed.join(", "))}">imputed</span>` : ""}</td><td>${fmt(r.model_aqi, 1)}<br><span class="small muted">XGBoost (${esc(r.estimate_time || "--")})${r.estimate_old ? " · old" : ""}</span></td><td>${chip(r.estimated_aqi, r.color)}<br><span class="small muted">API CPCB AQI (${esc(r.estimate_time || "--")})</span></td><td>${fmt(r.difference, 1)}</td><td>${esc(r.dominant || "--")}</td></tr>`
        : `<tr><td>${esc(r.city)}</td><td colspan="4" class="muted">${esc(r.error)}</td></tr>`).join("");
    }
    const okRows = rows.filter(r => r.ok);
    if (okRows.length && $("#compareChart")) {
      draw("compareChart", {
        type: "bar",
        data: {
          labels: okRows.map(r => r.city),
          datasets: [
            { label: "Predicted (XGBoost)", data: okRows.map(r => r.model_aqi), backgroundColor: "#38bdf8" },
            { label: "Actual (API CPCB AQI)", data: okRows.map(r => r.estimated_aqi), backgroundColor: "#059669" }
          ]
        },
        options: { scales: { y: { beginAtZero: true } } }
      });
    }
    const available = rows.filter(r => r.ok);
    if (summary) {
      summary.textContent = available.length
        ? `${available.length} districts compared. Differences are descriptive only, not accuracy scores.`
        : "No district could be compared.";
    }
    const note = $("#compareNote");
    if (note) note.textContent = d.note;
  } catch (e) {
    if (summary) summary.innerHTML = `<span class="alert err">${esc(e.message)}</span>`;
  }
  if (btn) {
    btn.disabled = false;
    btn.textContent = "Run comparison";
  }
}

async function loadOutlook() {
  const days = $("#daysSelect")?.value || 7;
  try {
    const d = await api(`/api/predict/outlook?days=${days}`);
    const rows = (d.rows || []).filter(r => r.ok && r.forecast && r.forecast.length);
    $("#outlookSummary").textContent = rows.length
      ? `First forecast-day AQI for ${rows.length} districts from the notebook XGBoost model.`
      : "District forecasts are unavailable.";
    if (!rows.length) return;
    draw("outlookChart", {
      type: "bar",
      data: {
        labels: rows.map(r => r.city),
        datasets: [{
          label: "Predicted AQI",
          data: rows.map(r => r.forecast[0].aqi),
          backgroundColor: rows.map(r => r.forecast[0].color || AQI_COLORS(r.forecast[0].aqi))
        }]
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
    });
  } catch (e) {
    $("#outlookSummary").textContent = e.message;
  }
}

async function loadMetrics() {
  try {
    const d = await api("/api/predict/direct-metrics");
    const metrics = Array.isArray(d && d.metrics) ? d.metrics : [];
    if (!metrics.length || !metrics.some(m => m.model_mae != null)) {
      $("#metricsNote").textContent = "Model MAE is not available for the direct-horizon metrics file, so this chart is hidden.";
      if (charts.metricsChart) {
        charts.metricsChart.destroy();
        delete charts.metricsChart;
      }
      return;
    }
    draw("metricsChart", {
      type: "bar",
      data: {
        labels: metrics.map(m => `t+${m.horizon_days ?? m.horizon ?? (metrics.indexOf(m) + 1)}`),
        datasets: [
          { label: "Model MAE", data: metrics.map(m => m.model_mae), backgroundColor: "#318cf1" },
          { label: "Persistence MAE", data: metrics.map(m => m.persistence_mae), backgroundColor: "#94a3b8" }
        ]
      },
      options: { scales: { y: { beginAtZero: true } } }
    });
  } catch (e) {
    $("#metricsNote").textContent = e.message;
  }
}

async function loadModelStatus() {
  try {
    const h = await api("/api/health");
    const model = h.model || {};
    $("#modelFileNote").textContent = model.loaded
      ? `${model.features || 64} production features loaded.`
      : `Model not loaded: ${model.error || "unknown error"}`;
  } catch (e) {
    $("#modelFileNote").textContent = e.message;
  }
}

function initPrediction() {
  $("#forecastBtn")?.addEventListener("click", () => { runForecast(); loadOutlook(); });
  if ($("#compareBtn")) {
    $("#compareBtn").addEventListener("click", runCompare);
  }
  loadModelStatus();
  runForecast();
  loadOutlook();
  if ($("#compareBtn")) {
    runCompare();
  }
  loadMetrics();
}

async function loadSensors() {
  const city = $("#citySelect").value;
  history.replaceState(null, "", `?city=${encodeURIComponent(city)}`);
  $("#aqiValue").textContent = "--";
  $("#aqiCategory").textContent = "Waiting for devices…";
  $("#pollutantGrid").innerHTML = "";
  alertBox($("#alertBox"), "", "");
  try {
    const d = await api(`/api/sensors/${encodeURIComponent(city)}?hours=48`);
    const latest = d.latest || {};
    const status = d.status || {};
    $("#sensorStatusLine").textContent = `${status.total_readings || 0} stored readings` + (status.last ? ` · last ${status.last.city} / ${status.last.device_id}` : "");
    if (!latest.ok) {
      $("#aqiCategory").textContent = latest.error || "No recent sensor data";
      alertBox($("#alertBox"), "info", latest.error || "No recent sensor readings. Devices should POST to /api/sensors/reading.");
    } else {
      $("#aqiValue").textContent = latest.aqi ?? "--";
      $("#aqiCategory").innerHTML = latest.aqi == null ? esc(latest.category || "Unavailable") : categoryBadge(latest.aqi, latest.category);
      $("#aqiBar").innerHTML = latest.aqi != null ? `<i style="left:${Math.min(latest.aqi, 500) / 5}%"></i>` : "";
      $("#healthText").textContent = latest.health || "";
      $("#dominantText").textContent = latest.dominant ? `${latest.dominant}: ${latest.dominant_info}` : "Not enough sensor pollutants for CPCB AQI.";
      $("#metaText").textContent = `Devices: ${(latest.devices || []).join(", ") || "--"} · ${latest.estimate_time || "--"}`;
      $("#pollutantGrid").innerHTML = (latest.pollutants || []).map(p => `
        <div class="pcard ${p.key === latest.dominant ? "dom" : ""}">
          <div class="name">${esc(p.label)}</div>
          <div class="val">${p.value === null ? "--" : fmt(p.value, p.key === "CO" ? 2 : 1)}</div>
          <div class="unit">${esc(p.unit)}</div>
          <div class="sub">${p.subindex === null ? "no data" : "sub-index " + fmt(p.subindex)}</div>
          <span class="tag sensor">Sensor</span>
        </div>`).join("");
    }
    const points = d.points || [];
    draw("sensorChart", {
      type: "line",
      data: { labels: points.map(p => p.t), datasets: [{ label: "Sensor AQI", data: points.map(p => p.aqi), borderColor: "#7b73f1", tension: .2 }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { maxTicksLimit: 6 } } } }
    });
    $("#sensorNote").textContent = points.length
      ? `${points.length} hardware readings in the last 48 hours.`
      : "Nothing stored yet. Once devices post to Flask, points appear here and in /api/sensors/export for Colab.";
  } catch (e) {
    alertBox($("#alertBox"), "err", e.message);
  }
}

function initSensors() {
  const q = new URLSearchParams(location.search).get("city");
  if (q) $("#citySelect").value = q;
  $("#citySelect").addEventListener("change", loadSensors);
  loadSensors();
  setInterval(loadSensors, 60 * 1000);
}

/* ------------------------------------------------------------ POLICY */
async function loadSources() {
  const city = $("#citySelect").value, box = $("#sourcesBody");
  box.innerHTML = "Loading…";
  try {
    const d = await api(`/api/sources/${encodeURIComponent(city)}`);
    let h = `<h3>Elevated pollutant indicators · ${esc(d.city)}</h3><p class="small muted">Based on: ${esc(d.basis)} · Calculated AQI ${d.aqi ?? "--"} (${esc(d.category)})</p>`;
    h += d.within_good ? `<div class="alert info">No pollutant sub-index is above the CPCB 'Good' threshold in this snapshot. This does not determine emission sources.</div>`
      : d.signals.map(s => `<div class="signal"><h4>${esc(s.source)} <span class="tag">${esc(s.label)} · ${fmt(s.score)}</span></h4><div class="small">${esc(s.explanation)}</div><ul>${s.evidence.map(e => `<li>${esc(e)}</li>`).join("")}</ul></div>`).join("");
    const m = d.seasonal;
    if (m.months.length) h += `<canvas id="seasonChart" height="110"></canvas><div class="small muted">Mean daily AQI by calendar month across ${m.n_days} days through ${esc(m.last_date || "--")}; descriptive seasonality only.</div>`;
    h += `<p class="small muted"><b>Note:</b> ${esc(d.caveat)}</p>`;
    box.innerHTML = h;
    if (m.months.length) {
      const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      draw("seasonChart", { type: "bar", data: { labels: m.months.map(i => names[i - 1]), datasets: [{ data: m.mean_aqi, backgroundColor: m.mean_aqi.map(AQI_COLORS) }] }, options: { plugins: { legend: { display: false } } } });
    }
  } catch (e) { box.innerHTML = `<div class="alert err">${esc(e.message)}</div>`; }
}

function tableHTML(t, title) {
  if (!t.found) return `<div class="card"><h3>${esc(title)}</h3><div class="alert warn">${esc(t.file)} was not found in the data/ folder.</div></div>`;
  const note = t.district_filtered ? `Showing ${t.matched} of ${t.total} rows for this district.` : `Showing ${t.matched} of ${t.total} rows${t.district_column ? "" : " (no district column detected, so rows are not filtered by district)"}.`;
  if (!t.rows.length) return `<div class="card"><h3>${esc(title)}</h3><p class="muted">No matching rows. ${esc(note)}</p></div>`;
  return `<div class="card"><h3>${esc(title)}</h3><p class="small muted">${esc(note)}${t.truncated ? " First 500 shown." : ""}</p><div class="table-wrap"><table class="tbl"><thead><tr>${t.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${t.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`;
}

async function loadPolicyCityOptions() {
  const select = $("#policyCitySelect");
  if (!select) return;
  try {
    const d = await api("/api/policy/districts");
    select.innerHTML = '<option value="">Select City/District</option>' + d.districts.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    const current = $("#citySelect")?.value || "Bengaluru";
    select.value = d.districts.includes(current) ? current : "Bengaluru";
  } catch (e) {
    select.innerHTML = '<option value="">Unavailable</option>';
  }
}

async function loadPolicyOptions() {
  const city = $("#policyCitySelect").value;
  const select = $("#policyPolicySelect");
  if (!city) {
    select.innerHTML = '<option value="">Select Policy</option>';
    select.disabled = true;
    $("#policyPollutants").textContent = "Affected pollutants will appear here after a policy is selected.";
    return;
  }
  select.disabled = true;
  try {
    const d = await api(`/api/policy/policies/${encodeURIComponent(city)}`);
    if (!d.policies || !d.policies.length) {
      select.innerHTML = '<option value="">No policies assigned</option>';
      $("#policyPollutants").textContent = "No policy is assigned to this city yet.";
      select.disabled = true;
      return;
    }
    select.innerHTML = '<option value="">Select Policy</option>' + d.policies.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
    select.disabled = false;
  } catch (e) {
    select.innerHTML = '<option value="">Unavailable</option>';
    select.disabled = true;
  }
}

async function analyzeSelectedPolicy() {
  const city = $("#policyCitySelect").value;
  const policy = $("#policyPolicySelect").value;
  const windowMonths = Number($("#policyWindowSelect").value || 3);
  const pollutants = $("#policyPollutants");
  const summary = $("#policySummary");
  const rec = $("#policyRecommendation");
  const summaryCity = $("#summaryCity");
  const summaryPolicy = $("#summaryPolicy");
  const summaryPollutants = $("#summaryPollutants");
  const summaryImpact = $("#summaryImpact");
  const insights = $("#policyInsights");

  if (!city || !policy) {
    pollutants.textContent = "Affected pollutants will appear here after a policy is selected.";
    summary.innerHTML = "";
    rec.textContent = "";
    if (summaryCity) summaryCity.textContent = "-";
    if (summaryPolicy) summaryPolicy.textContent = "-";
    if (summaryPollutants) summaryPollutants.textContent = "-";
    if (summaryImpact) summaryImpact.textContent = "-";
    if (insights) insights.innerHTML = "";
    return;
  }

  try {
    const d = await api("/api/policy/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ city, policy, window_months: windowMonths })
    });

    summaryCity.textContent = esc(d.city || city);
    summaryPolicy.textContent = esc(d.policy || policy);
    summaryPollutants.textContent = d.affected_pollutants.length ? d.affected_pollutants.join(", ") : "-";
    summaryImpact.textContent = esc(d.status || "-" );

    pollutants.innerHTML = d.affected_pollutants.map(p => `<span class="tag" style="margin-right:6px;">${esc(p)}</span>`).join("") || "No pollutants mapped.";

    summary.innerHTML = `
      <p class="summary-line">${esc(d.policy)} was analyzed using a ${esc(d.window_months)}-month before-and-after window. Before measurements: ${esc(d.periods.before_start)} to ${esc(d.periods.before_end)}; after measurements: ${esc(d.periods.after_start)} to ${esc(d.periods.after_end)}.</p>
      <p class="summary-line">Improved ${esc(d.results.filter(r => r.change_pct >= 5).length)} out of ${esc(d.results.length)} pollutants.</p>
      <p class="summary-line">Overall impact: <strong>${esc(d.status)}</strong></p>
    `;

    const improvedPollutants = d.results.filter(r => r.change_pct >= 5).map(r => r.pollutant);
    const worsenedPollutants = d.results.filter(r => r.change_pct < 0).map(r => r.pollutant);
    const insightItems = [];
    if (improvedPollutants.length) insightItems.push(`<li>Improved pollutants: ${improvedPollutants.map(p => esc(p)).join(", ")}</li>`);
    if (worsenedPollutants.length) insightItems.push(`<li>Increased pollutants: ${worsenedPollutants.map(p => esc(p)).join(", ")}</li>`);
    if (!insightItems.length) insightItems.push(`<li>No clear pollutant trend change detected in this window.</li>`);
    insights.innerHTML = insightItems.join("");

    rec.textContent = d.recommendation || "";

    draw("policyChart", {
      type: "bar",
      data: {
        labels: d.results.map(r => r.pollutant),
        datasets: [
          { label: "Before policy", data: d.results.map(r => r.before), backgroundColor: "#7db8e8" },
          { label: "After policy", data: d.results.map(r => r.after), backgroundColor: "#f2a9b0" }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true }, tooltip: { enabled: true } },
        scales: { y: { beginAtZero: false, title: { display: true, text: "Mean concentration" } } }
      }
    });
  } catch (e) {
    pollutants.textContent = "Unable to compute selected policy impact.";
    summary.innerHTML = `<div class="alert err">${esc(e.message)}</div>`;
    rec.textContent = "";
    if (summaryCity) summaryCity.textContent = "-";
    if (summaryPolicy) summaryPolicy.textContent = "-";
    if (summaryPollutants) summaryPollutants.textContent = "-";
    if (summaryImpact) summaryImpact.textContent = "-";
    if (insights) insights.innerHTML = "";
  }
}
function initPolicy() {
  const city = $("#policyCitySelect");
  const policy = $("#policyPolicySelect");
  const windowSelect = $("#policyWindowSelect");

  if (city) {
    loadPolicyCityOptions().then(() => {
      if (city.value) loadPolicyOptions();
    });
    city.addEventListener("change", () => loadPolicyOptions());
  }

  const analyzeBtn = $("#policyAnalyzeBtn");
  if (policy) policy.addEventListener("change", analyzeSelectedPolicy);
  if (windowSelect) windowSelect.addEventListener("change", () => {
    if (policy && policy.value) analyzeSelectedPolicy();
  });
  if (analyzeBtn) analyzeBtn.addEventListener("click", analyzeSelectedPolicy);
}

function initInsights() {
  const citySelect = $("#citySelect");
  if (!citySelect) return;

  citySelect.addEventListener("change", loadSources);
  loadSources();
}

/* ------------------------------------------------------------ boot */
document.addEventListener("DOMContentLoaded", () => {
  const navToggle = $("#navToggle");
  const primaryNav = $("#primaryNav");
  if (navToggle && primaryNav) {
    navToggle.addEventListener("click", () => {
      const expanded = navToggle.getAttribute("aria-expanded") === "true";
      navToggle.setAttribute("aria-expanded", String(!expanded));
      navToggle.setAttribute("aria-label", expanded ? "Open navigation" : "Close navigation");
      primaryNav.classList.toggle("nav-open", !expanded);
    });
    primaryNav.addEventListener("click", event => {
      if (event.target.closest("a")) {
        navToggle.setAttribute("aria-expanded", "false");
        navToggle.setAttribute("aria-label", "Open navigation");
        primaryNav.classList.remove("nav-open");
      }
    });
  }
  const page = document.body.dataset.page;
  if (page === "home") initHome();
  else if (page === "monitoring") initMonitoring();
  else if (page === "sensors") initSensors();
  else if (page === "prediction") initPrediction();
  else if (page === "insights") initInsights();
  else if (page === "policy") initPolicy();
});
