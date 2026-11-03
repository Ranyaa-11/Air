"""
AIRWISE Future AQI Prediction

Uses the saved AIRWISE XGBoost production model and the exact
64-feature list stored in airwise_production_features.pkl.

The feature construction follows the final Colab prediction logic.
"""

import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import joblib
from xgboost import XGBRegressor, __version__ as XGBOOST_VERSION

from . import aqi_service as aqi
from .data_service import (
    data_service,
    CITIES,
    BASE_DIR
)
from .monitoring_service import monitoring_service


# ============================================================
# MODEL FILES
# ============================================================

MODEL_PATH = os.path.join(
    BASE_DIR,
    "models",
    "airwise_xgboost_production_model.pkl"
)

MODEL_JSON_PATH = os.path.join(
    BASE_DIR,
    "models",
    "airwise_xgboost_production_model.json"
)

FEATURES_PATH = os.path.join(
    BASE_DIR,
    "models",
    "airwise_production_features.pkl"
)


KNOWN_DAY_VALIDATION = (
    "From the notebook: MAE 1.05, RMSE 3.65, R2 0.9854 for same-day estimates "
    "when that day's pollutants are known. This is not forecast accuracy."
)


def build_outlook_schedule(last_date, requested_days, anchor_date=None):
    """Build the forecast schedule from the actual first forecast anchor date.

    When live CPCBCCR pollutant values are available for the current day, the first forecast row
    should use that anchor date instead of defaulting to the last historical record + 1 day.
    """
    last = pd.Timestamp(last_date)
    if last.tz is None:
        last = last.tz_localize("Asia/Kolkata")
    else:
        last = last.tz_convert("Asia/Kolkata")
    last = last.normalize()

    if anchor_date is not None:
        anchor = pd.Timestamp(anchor_date)
        if anchor.tz is None:
            anchor = anchor.tz_localize("Asia/Kolkata")
        else:
            anchor = anchor.tz_convert("Asia/Kolkata")
        anchor = anchor.normalize()
        if anchor < last:
            anchor = last + pd.Timedelta(days=1)
    else:
        anchor = last + pd.Timedelta(days=1)

    requested_days = max(1, int(requested_days))
    schedule = [
        (anchor + pd.Timedelta(days=offset), False, offset + 1)
        for offset in range(requested_days)
    ]
    return schedule, 0, anchor


class PredictionService:

    def __init__(self):

        self._model = None
        self._features = None
        self._error = None
        self._lock = threading.Lock()


    # ========================================================
    # LOAD MODEL
    # ========================================================

    def _load(self):

        with self._lock:

            if (
                self._model is not None
                or self._error is not None
            ):
                return

            try:

                if not os.path.exists(MODEL_JSON_PATH) and not os.path.exists(MODEL_PATH):
                    raise FileNotFoundError(
                        "No production model found. Expected "
                        f"{MODEL_JSON_PATH} or {MODEL_PATH}"
                    )

                if not os.path.exists(FEATURES_PATH):
                    raise FileNotFoundError(
                        f"Feature file not found: {FEATURES_PATH}"
                    )

                self._features = list(
                    joblib.load(
                        FEATURES_PATH
                    )
                )

                if len(self._features) != 64:
                    raise ValueError(
                        f"Expected 64 production features, "
                        f"found {len(self._features)}"
                    )

                if os.path.exists(MODEL_JSON_PATH):
                    model = XGBRegressor()
                    model.load_model(MODEL_JSON_PATH)
                else:
                    try:
                        model = joblib.load(MODEL_PATH)
                    except Exception as e:
                        raise RuntimeError(
                            "Could not load the legacy XGBoost pickle with "
                            f"XGBoost {XGBOOST_VERSION}: {e}. Export the trained "
                            "model as airwise_xgboost_production_model.json from "
                            "the Colab runtime and place it in the models folder."
                        ) from e

                feature_count = model.get_booster().num_features()
                if feature_count != len(self._features):
                    raise ValueError(
                        f"Model expects {feature_count} features but the "
                        f"production feature list has {len(self._features)}"
                    )

                self._model = model

            except Exception as e:

                self._error = (
                    f"{type(e).__name__}: {e}"
                )


    # ========================================================
    # MODEL STATUS
    # ========================================================

    def status(self):

        self._load()

        return {
            "loaded":
                self._model is not None,

            "error":
                self._error,

            "features":
                len(self._features)
                if self._features is not None
                else 0,

            "known_day_validation":
                KNOWN_DAY_VALIDATION,

            "model_file":
                "airwise_xgboost_production_model.json"
                if os.path.exists(MODEL_JSON_PATH)
                else (
                    "airwise_xgboost_production_model.pkl"
                    if os.path.exists(MODEL_PATH)
                    else None
                ),
        }


    # ========================================================
    # CREATE ONE FUTURE FEATURE ROW
    #
    # Based on final Colab create_future_features()
    # ========================================================

    def _features_row(
        self,
        city,
        future_date,
        history,
        future_pollutants
    ):

        future_date = pd.Timestamp(
            future_date
        )

        row = {}

        # ----------------------------------------------------
        # Pollutants
        # ----------------------------------------------------

        for pollutant in aqi.POLLUTANTS:

            value = future_pollutants.get(
                pollutant
            )

            row[pollutant] = value

        # ----------------------------------------------------
        # CPCB pollutant sub-indices
        # ----------------------------------------------------

        sub_values = []

        for pollutant in aqi.POLLUTANTS:

            value = future_pollutants.get(
                pollutant
            )

            subindex = aqi.subindex(
                value,
                pollutant
            )

            row[
                f"{pollutant}_SUBINDEX"
            ] = subindex

            if subindex is not None:

                sub_values.append(
                    subindex
                )

        row["SUBINDEX_MEAN"] = (
            np.mean(sub_values)
            if sub_values
            else np.nan
        )

        # IMPORTANT:
        # Training uses pandas .std()
        # which is sample std, ddof=1.
        row["SUBINDEX_STD"] = (
            np.std(
                sub_values,
                ddof=1
            )
            if len(sub_values) > 1
            else np.nan
        )

        row["SUBINDEX_VALID_COUNT"] = (
            len(sub_values)
        )

        # ----------------------------------------------------
        # Time features
        # ----------------------------------------------------

        row["Year"] = (
            future_date.year
        )

        row["Month"] = (
            future_date.month
        )

        row["Day"] = (
            future_date.day
        )

        row["DayOfWeek"] = (
            future_date.dayofweek
        )

        row["DayOfYear"] = (
            future_date.dayofyear
        )

        row["WeekOfYear"] = int(
            future_date.isocalendar().week
        )

        row["Month_Sin"] = np.sin(
            2 * np.pi
            * future_date.month
            / 12
        )

        row["Month_Cos"] = np.cos(
            2 * np.pi
            * future_date.month
            / 12
        )

        row["DayOfWeek_Sin"] = np.sin(
            2 * np.pi
            * future_date.dayofweek
            / 7
        )

        row["DayOfWeek_Cos"] = np.cos(
            2 * np.pi
            * future_date.dayofweek
            / 7
        )

        # ----------------------------------------------------
        # AQI LOG history
        # ----------------------------------------------------

        if len(history) == 0:

            raise ValueError(
                f"No AQI history available for {city}"
            )

        latest_aqi_log = (
            history[-1]
        )

        # ----------------------------------------------------
        # AQI lags 1–15
        # ----------------------------------------------------

        for lag in range(1, 16):

            if len(history) >= lag:

                row[
                    f"AQI_LAG_{lag}"
                ] = history[-lag]

            else:

                row[
                    f"AQI_LAG_{lag}"
                ] = latest_aqi_log

        # ----------------------------------------------------
        # Rolling features
        # ----------------------------------------------------

        recent_3 = history[-3:]
        recent_7 = history[-7:]

        row[
            "AQI_ROLL_MEAN_3D"
        ] = np.mean(recent_3)

        row[
            "AQI_ROLL_STD_3D"
        ] = (
            np.std(
                recent_3,
                ddof=1
            )
            if len(recent_3) > 1
            else np.nan
        )

        row[
            "AQI_ROLL_MEAN_7D"
        ] = np.mean(recent_7)

        # ----------------------------------------------------
        # Previous-day pollutants
        #
        # Final Colab obtains these from latest city data.
        # Here future_pollutants are held at latest values,
        # so the same values are used.
        # ----------------------------------------------------

        for pollutant in aqi.POLLUTANTS:

            row[
                f"{pollutant}_LAG_1"
            ] = future_pollutants.get(
                pollutant
            )

        # ----------------------------------------------------
        # Previous-day AQI
        # ----------------------------------------------------

        row["AQI_PREV_DAY"] = (
            latest_aqi_log
        )

        # ----------------------------------------------------
        # CITY one-hot
        #
        # IMPORTANT:
        # We use the exact names in the saved
        # airwise_production_features.pkl.
        # ----------------------------------------------------

        for city_name in CITIES:

            row[
                f"CITY_{city_name}"
            ] = (
                1
                if city_name == city
                else 0
            )

        # ----------------------------------------------------
        # Exact production feature order
        # ----------------------------------------------------

        X = pd.DataFrame(
            [row]
        )

        X = X.reindex(
            columns=self._features,
            fill_value=0
        )

        X = X.apply(
            pd.to_numeric,
            errors="coerce"
        )

        X = X.replace(
            [np.inf, -np.inf],
            np.nan
        )

        # Same final safety used in Colab
        X = X.fillna(0)

        return X


    # ========================================================
    # MODEL PREDICTION
    # ========================================================

    def _predict(self, X):

        predicted_log = float(
            self._model.predict(X)[0]
        )

        predicted_aqi = max(
            0,
            float(
                np.expm1(
                    predicted_log
                )
            )
        )

        return (
            predicted_log,
            predicted_aqi
        )


    # ========================================================
    # GET HISTORICAL CONTEXT
    # ========================================================

    def _context(self, city):

        history, last_date = (
            data_service.aqi_log_history(
                city
            )
        )

        pollutants, pollutant_date = (
            data_service.latest_pollutants(
                city
            )
        )

        if not history:

            raise ValueError(
                f"No AQI history available for {city}. "
                f"Run prepare_data.py first."
            )

        if pollutants is None:

            raise ValueError(
                f"No pollutant data available for {city}."
            )

        clean_pollutants = {}

        for pollutant in aqi.POLLUTANTS:
            value = pollutants.get(pollutant)
            if value is None or pd.isna(value):
                clean_pollutants[pollutant] = 0.0
            else:
                clean_pollutants[pollutant] = float(value)

        return (
            list(history),
            last_date,
            clean_pollutants,
            pollutant_date
        )

    def _live_or_historical_pollutants(self, city):
        """Use live CPCB pollutant values when valid, otherwise fall back to the latest historical profile."""
        live = monitoring_service.current(city)
        values = {}
        if live.get("ok") and isinstance(live.get("values"), dict):
            values = {
                pollutant: float(value)
                for pollutant, value in live["values"].items()
                if value is not None and not pd.isna(value)
            }

        if not values:
            history, last_date = data_service.aqi_log_history(city)
            historical = data_service.latest_pollutants(city)[0] or {}
            if not historical:
                raise ValueError(f"No live or historical pollutant data available for {city}.")
            values = {p: float(v) for p, v in historical.items() if v is not None and not pd.isna(v)}
            actual_reference_date = last_date.strftime("%Y-%m-%d") if last_date is not None else None
            fallback_warning = "Historical fallback used: live API data unavailable or invalid; forecast input reference date is the latest valid historical day."
            return values, actual_reference_date, fallback_warning

        return values, live.get("estimate_time") or None, None


    # ========================================================
    # FORECAST BASIS
    # ========================================================

    def _basis(
        self,
        last_date,
        pollutant_date
    ):

        today = pd.Timestamp(
            datetime.now(ZoneInfo("Asia/Kolkata")).date()
        )

        age = (
            today - last_date
        ).days

        return {

            "history_ends":
                last_date.strftime(
                    "%Y-%m-%d"
                ),

            "history_age_days":
                int(age),

            "pollutants_from":
                pollutant_date.strftime(
                    "%Y-%m-%d"
                )
                if pollutant_date is not None
                else None,

            "stale":
                age > 3,

            "assumption":
                "Forward-looking projection using the latest available district pollutant context and historical AQI lags. It is not weather-aware and is not a validated multi-day forecast."
        }


    # ========================================================
    # TOMORROW
    # ========================================================

    def tomorrow(self, city):

        return self.forecast(
            city,
            1
        )


    # ========================================================
    # FUTURE FORECAST
    # ========================================================

    def forecast(
        self,
        city,
        days=7,
    ):

        self._load()

        if self._model is None:

            raise RuntimeError(
                "Prediction model could not be loaded: "
                + str(self._error)
            )

        requested_days = max(1, int(days))

        (
            history,
            last_date,
            pollutants,
            pollutant_date
        ) = self._context(city)

        live_pollutants, live_reference, historical_warning = self._live_or_historical_pollutants(city)
        if live_pollutants:
            pollutants = {**pollutants, **{p: float(v) for p, v in live_pollutants.items() if p in aqi.POLLUTANTS}}

        anchor_date = None
        if live_reference:
            try:
                raw_anchor = str(live_reference).strip()
                if raw_anchor.endswith(" IST"):
                    raw_anchor = raw_anchor[:-4].strip()
                elif raw_anchor.endswith(" UTC"):
                    raw_anchor = raw_anchor[:-4].strip()
                anchor_date = pd.Timestamp(raw_anchor)
                if anchor_date.tz is None:
                    anchor_date = anchor_date.tz_localize("Asia/Kolkata")
                else:
                    anchor_date = anchor_date.tz_convert("Asia/Kolkata")
                anchor_date = anchor_date.normalize()
            except Exception:
                anchor_date = None

        if anchor_date is None:
            anchor_date = last_date + pd.Timedelta(days=1)

        working_history = list(history)
        forecast_pollutants = dict(pollutants)
        schedule, _, first_outlook_date = build_outlook_schedule(
            last_date, requested_days, anchor_date=anchor_date
        )

        results = []
        for future_date, _, days_ahead in schedule:
            X = self._features_row(
                city,
                future_date,
                working_history,
                forecast_pollutants
            )

            predicted_log, predicted_aqi = self._predict(X)
            results.append({
                "date": future_date.strftime("%Y-%m-%d"),
                "day": future_date.strftime("%a"),
                "aqi": int(round(predicted_aqi)),
                "category": aqi.category(predicted_aqi),
                "color": aqi.color(predicted_aqi),
                "value_type": "Notebook XGBoost forecast",
                "days_ahead": days_ahead,
            })
            working_history.append(predicted_log)

        basis = {
            **self._basis(last_date, pollutant_date),
            "anchor": "live_cpcb" if live_reference else "historical",
            "anchor_date": anchor_date.strftime("%Y-%m-%d"),
            "gap_filled_days": 0,
            "outlook_start": first_outlook_date.strftime("%Y-%m-%d"),
            "input_reference_date": live_reference or last_date.strftime("%Y-%m-%d"),
            "forecast_start_date": first_outlook_date.strftime("%Y-%m-%d"),
            "historical_fallback_used": bool(historical_warning),
            "historical_fallback_warning": historical_warning,
        }
        return {"city": city, "forecast": results, "basis": basis}


    # ========================================================
    # TODAY VS REAL-TIME
    #
    # Used by comparison_service.py
    # ========================================================

    def nowcast(
        self,
        city,
        live_values
    ):

        self._load()

        if self._model is None:

            raise RuntimeError(
                "Prediction model could not be loaded: "
                + str(self._error)
            )

        (
            history,
            last_date,
            historical_pollutants,
            pollutant_date
        ) = self._context(city)

        pollutants = {}
        imputed = []

        # ----------------------------------------------------
        # Use live values when available.
        # Missing values come from historical data.
        # ----------------------------------------------------

        for pollutant in aqi.POLLUTANTS:

            value = aqi._num(
                live_values.get(
                    pollutant
                )
            )

            if value is None:

                value = (
                    historical_pollutants.get(
                        pollutant
                    )
                )

                imputed.append(
                    pollutant
                )

            pollutants[pollutant] = value

        X = self._features_row(
            city,
            pd.Timestamp.now().normalize(),
            history,
            pollutants
        )

        _, xgb_aqi = self._predict(
            X
        )

        return {

            "xgb_aqi":
                xgb_aqi,

            "imputed":
                imputed,

            "pollutants":
                pollutants,

            "basis":
                self._basis(
                    last_date,
                    pollutant_date
                )
        }


prediction_service = PredictionService()