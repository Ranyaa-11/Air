"""Policy analysis.

Browse the project's Excel workbooks (Policy.xlsx, DistrictPolicy.xlsx,
Disdata.xlsx). Their column layout is not known to the code, so tables are
shown exactly as stored; the district column is auto-detected.
"""
import os
import threading
import pandas as pd

from . import aqi_service as aqi
from .aqi_service import UNITS
from .data_service import DATA_DIR, CITY_ALIASES, CITIES, data_service
from .monitoring_service import monitoring_service

FILES = {"policy": "Policy.xlsx", "district_policy": "DistrictPolicy.xlsx", "district_data": "Disdata.xlsx"}
MAX_ROWS = 500


class PolicyService:
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def _load(self, key):
        path = os.path.join(DATA_DIR, FILES[key])
        if not os.path.exists(path):
            return None
        mtime = os.path.getmtime(path)
        with self._lock:
            hit = self._cache.get(key)
            if hit and hit[0] == mtime:
                return hit[1]
        sheets = pd.read_excel(path, sheet_name=None)
        frames = []
        for name, df in sheets.items():
            df = df.dropna(how="all").dropna(axis=1, how="all")
            df.columns = [str(c).strip() for c in df.columns]
            if len(sheets) > 1:
                df.insert(0, "Sheet", name)
            frames.append(df)
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        with self._lock:
            self._cache[key] = (mtime, df)
        return df

    @staticmethod
    def _district_col(df):
        for c in df.columns:
            if any(k in c.lower() for k in ("district", "city", "dist")):
                return c
        return None

    @staticmethod
    def _records(df):
        df = df.head(MAX_ROWS).copy()
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                df[c] = df[c].dt.strftime("%Y-%m-%d")
        df = df.astype(object).where(df.notna(), "")
        return {"columns": list(df.columns), "rows": df.astype(str).values.tolist()}

    @staticmethod
    def _normalize_city_name(name):
        if name is None:
            return ""
        text = str(name).strip()
        if not text:
            return ""
        text = text.replace("_", " ").strip()
        aliases = {
            "Bagalkote": "Bagalkot",
            "Belagaum": "Belgaum",
            "Belagavi": "Belgaum",
            "Bangalore": "Bengaluru",
            "Chikkamagalur": "Chikkamagaluru",
            "Chik Ballapur": "Chikkaballapur",
            "Mysore": "Mysuru",
            "Ramanagar": "Ramanagara",
            "Tumkur": "Tumakuru",
            "Yadgiri": "Yadgir",
            "Mangaluru": "Mangalore",
        }
        return aliases.get(text, text)

    @staticmethod
    def _normalize_pollutant_name(name):
        if name is None:
            return ""
        text = str(name).strip().upper().replace(" ", "")
        aliases = {"PM25": "PM2.5", "PM2_5": "PM2.5", "PM2.5": "PM2.5", "PM10": "PM10",
                   "O3": "OZONE", "OZONE": "OZONE", "NO2": "NO2", "SO2": "SO2", "CO": "CO"}
        return aliases.get(text, text)

    def addresses(self):
        return list(CITIES)

    def districts(self):
        names = set(self.addresses())
        for key in ("district_policy", "district_data"):
            df = self._load(key)
            if df is None:
                continue
            dcol = self._district_col(df)
            if not dcol:
                continue
            for value in df[dcol].dropna().astype(str):
                cleaned = self._normalize_city_name(value)
                if cleaned:
                    names.add(cleaned)
        return sorted(names, key=lambda n: n.lower())

    def policies_for_district(self, district):
        df = self._load("district_policy")
        if df is None:
            return []
        dcol = self._district_col(df)
        if not dcol:
            return []
        district = self._normalize_city_name(district)
        if not district:
            return []
        target = district.lower()
        values = df[dcol].astype(str).str.strip()
        lookup = values.map(lambda s: self._normalize_city_name(s).lower())
        matches = df[lookup == target]
        if matches.empty and district not in self.addresses():
            canonical = self._normalize_city_name(district)
            lookup = values.map(lambda s: self._normalize_city_name(s).lower())
            matches = df[lookup == canonical.lower()]
        policies = [str(v).strip() for v in matches["Policy"].dropna().astype(str)]
        return list(dict.fromkeys(policies))

    def pollutants_for_policy(self, policy):
        df = self._load("policy")
        if df is None:
            return []
        policy = str(policy).strip()
        if not policy:
            return []
        matches = df.loc[df["Policy_Name"].astype(str).str.strip().str.lower() == policy.lower()]
        if matches.empty and "Policy_ID" in df.columns:
            try:
                value = int(policy)
            except ValueError:
                value = None
            if value is not None:
                matches = df.loc[df["Policy_ID"] == value]
        values = []
        for cell in matches["Affected_Pollutants"].dropna().astype(str):
            values.extend([self._normalize_pollutant_name(v) for v in cell.split(",") if v.strip()])
        return list(dict.fromkeys([v for v in values if v]))

    def overview(self):
        out = {}
        for key, fname in FILES.items():
            df = self._load(key)
            out[key] = {"file": fname, "found": df is not None,
                        "rows": 0 if df is None else int(len(df)),
                        "columns": [] if df is None else list(df.columns),
                        "district_column": None if df is None else self._district_col(df)}
        return out

    def table(self, key, district=None, q=None):
        if key not in FILES:
            raise KeyError(key)
        df = self._load(key)
        if df is None:
            return {"found": False, "file": FILES[key]}
        total = len(df)
        dcol = self._district_col(df)
        if district and dcol:
            names = {district.lower()} | {a.lower() for a, c in CITY_ALIASES.items() if c == district}
            col = df[dcol].astype(str).str.strip().str.lower()
            df = df[col.isin(names)]
        if q:
            mask = df.astype(str).apply(lambda s: s.str.contains(q, case=False, na=False, regex=False)).any(axis=1)
            df = df[mask]
        out = self._records(df)
        out.update({"found": True, "file": FILES[key], "district_column": dcol, "matched": int(len(df)),
                    "total": total, "truncated": len(df) > MAX_ROWS,
                    "district_filtered": bool(district and dcol)})
        return out

    def policy_start_date(self, policy_name):
        df = self._load("policy")
        if df is None:
            return None
        if "Policy_Name" not in df.columns:
            return None
        match = df.loc[df["Policy_Name"].astype(str).str.strip().str.lower() == str(policy_name).strip().lower()]
        if match.empty:
            return None
        start = match.iloc[0].get("Start_Date")
        if pd.isna(start):
            return None
        try:
            return pd.to_datetime(start).strftime("%Y-%m-%d")
        except Exception:
            return str(start)

    @staticmethod
    def _window_bounds(policy_start, months):
        start = pd.to_datetime(policy_start)
        before_end = start - pd.Timedelta(days=1)
        before_start = start - pd.DateOffset(months=months)
        after_start = start
        after_end = after_start + (before_end - before_start)
        return {
            "before_start": before_start.normalize(),
            "before_end": before_end.normalize(),
            "after_start": after_start.normalize(),
            "after_end": after_end.normalize(),
        }

    @staticmethod
    def _valid_imputed_mask(frame, pollutant):
        series = pd.to_numeric(frame[pollutant], errors="coerce")
        mask = series.notna()
        lower = pollutant.lower().replace(" ", "")
        for col in frame.columns:
            key = str(col).strip().lower().replace(" ", "")
            if key in {f"{lower}_imputed", f"{lower}_flag", f"{lower}_is_imputed", f"{lower}_missing", f"imputed_{lower}", f"flag_{lower}"}:
                values = frame[col].astype(str).str.strip().str.lower()
                mask &= ~values.isin({"1", "true", "y", "yes", "imputed", "missing"})
        return mask

    @staticmethod
    def _pollutant_unit(pollutant):
        unit = UNITS.get(str(pollutant).strip().upper(), UNITS.get(str(pollutant).strip().title(), "µg/m³"))
        return unit.replace("OZONE", "Ozone") if False else unit

    @staticmethod
    def _compute_change_pct(before_mean, after_mean):
        if before_mean is None or pd.isna(before_mean) or before_mean == 0:
            return None
        if after_mean is None or pd.isna(after_mean):
            return None
        return ((after_mean - before_mean) / before_mean) * 100.0

    @staticmethod
    def classify_effectiveness(results):
        valid = []
        for row in results or []:
            value = row.get("change_pct") if isinstance(row, dict) else None
            if value is None or pd.isna(value):
                continue
            valid.append(float(value))
        if not valid:
            return "Low Impact"
        reduced = sum(1 for value in valid if value < 0)
        ratio = (reduced / len(valid)) * 100.0
        if ratio >= 70.0:
            return "Highly Effective"
        if ratio >= 40.0:
            return "Moderately Effective"
        return "Low Impact"

    def analyze(self, district, policy_name, window_months=1):
        district = self._normalize_city_name(district)
        if not district:
            raise ValueError("District is required")
        try:
            months = int(window_months)
        except (TypeError, ValueError):
            months = 1
        months = max(1, min(6, months))

        affected = self.pollutants_for_policy(policy_name)
        if not affected:
            raise ValueError(f"Policy '{policy_name}' has no pollutant list in Policy.xlsx")

        policy_start = self.policy_start_date(policy_name)

        df = self._load("district_data")
        if df is None:
            raise FileNotFoundError("Disdata.xlsx is missing from data/")
        city_col = self._district_col(df) or "City"
        if city_col not in df.columns:
            raise ValueError("Disdata.xlsx does not contain a district column")

        city_values = df[city_col].astype(str).str.strip().map(self._normalize_city_name)
        district_matches = city_values.str.lower() == district.lower()
        city_df = df.loc[district_matches].copy()
        if city_df.empty:
            raise ValueError(f"No district data found for '{district}'")

        city_df["Date"] = pd.to_datetime(city_df["Date"], errors="coerce")
        city_df = city_df.dropna(subset=["Date"]).sort_values("Date")
        if city_df.empty:
            raise ValueError(f"No valid dates found for '{district}'")

        if policy_start:
            bounds = self._window_bounds(policy_start, months)
            before_start = bounds["before_start"]
            before_end = bounds["before_end"]
            after_start = bounds["after_start"]
            after_end = bounds["after_end"]
        else:
            before_start = city_df["Date"].min()
            before_end = city_df["Date"].max()
            after_start = city_df["Date"].min()
            after_end = city_df["Date"].max()

        before_df = city_df[(city_df["Date"] >= before_start) & (city_df["Date"] <= before_end)] if policy_start else city_df
        after_df = city_df[(city_df["Date"] >= after_start) & (city_df["Date"] <= after_end)] if policy_start else city_df

        if policy_start and (before_df.empty or after_df.empty):
            before_df = city_df[city_df["Date"] <= (pd.to_datetime(policy_start) - pd.Timedelta(days=1))]
            after_df = city_df[city_df["Date"] >= pd.to_datetime(policy_start)]

        rows = []
        for pollutant in affected:
            if pollutant not in city_df.columns:
                continue
            before_mask = self._valid_imputed_mask(before_df, pollutant)
            after_mask = self._valid_imputed_mask(after_df, pollutant)
            before_vals = pd.to_numeric(before_df.loc[before_mask, pollutant], errors="coerce")
            after_vals = pd.to_numeric(after_df.loc[after_mask, pollutant], errors="coerce")
            before_vals = before_vals.dropna()
            after_vals = after_vals.dropna()
            if before_vals.empty or after_vals.empty:
                continue
            before = float(before_vals.mean())
            after = float(after_vals.mean())
            change_pct = self._compute_change_pct(before, after)
            rows.append({
                "pollutant": pollutant,
                "before": round(before, 2),
                "after": round(after, 2),
                "before_mean": round(before, 2),
                "after_mean": round(after, 2),
                "before_valid_days": int(len(before_vals)),
                "after_valid_days": int(len(after_vals)),
                "unit": self._pollutant_unit(pollutant),
                "change_pct": None if change_pct is None else round(change_pct, 1),
                "impact": "No Impact",
                "policy_start_date": policy_start,
            })

        if not rows:
            raise ValueError(f"No pollutant data found for {district} in the selected window")

        valid_rows = [r for r in rows if r["change_pct"] is not None]
        if valid_rows:
            reduced_count = sum(1 for r in valid_rows if r["change_pct"] < 0)
            improved_pct = (reduced_count / len(valid_rows)) * 100.0
            status = "Highly Effective" if improved_pct >= 70.0 else "Moderately Effective" if improved_pct >= 40.0 else "Low Impact"
            improved_label = "reduced"
        else:
            improved_pct = 0.0
            reduced_count = 0
            status = "Low Impact"
            improved_label = "reduced"

        for row in rows:
            if row["change_pct"] is None:
                row["impact"] = "No Impact"
            elif row["change_pct"] < 0:
                row["impact"] = "Reduced"
            elif row["change_pct"] > 0:
                row["impact"] = "Increased"
            else:
                row["impact"] = "No Change"

        avg_before = sum(r["before"] for r in rows) / len(rows)
        avg_after = sum(r["after"] for r in rows) / len(rows)
        overall_change_pct = self._compute_change_pct(avg_before, avg_after)
        if overall_change_pct is None:
            overall_change_pct = 0.0

        summary = (
            f"For {district}, {policy_name} shows {reduced_count} of {len(valid_rows)} affected pollutants reduced "
            f"({improved_pct:.1f}%) over the selected {months}-month analysis window."
        )
        recommendation = (
            f"{policy_name} was implemented on {policy_start or 'unknown date'} and the observed impact is {status.lower()} for {district}. "
            "Review pollutant-specific trends and continue enforcement where reductions remain limited."
        )

        result = {
            "city": district,
            "district": district,
            "policy": policy_name,
            "implementation_date": policy_start,
            "window_months": months,
            "periods": {
                "before_start": before_start.strftime("%Y-%m-%d"),
                "before_end": before_end.strftime("%Y-%m-%d"),
                "after_start": after_start.strftime("%Y-%m-%d"),
                "after_end": after_end.strftime("%Y-%m-%d"),
            },
            "affected_pollutants": [r["pollutant"] for r in rows],
            "results": rows,
            "status": status,
            "summary": summary,
            "recommendation": recommendation,
            "before_avg": round(avg_before, 2),
            "after_avg": round(avg_after, 2),
            "overall_change_pct": round(overall_change_pct, 1),
            "reduced_pollutant_count": reduced_count,
            "total_valid_pollutants": len(valid_rows),
            "reduction_percent": round(improved_pct, 1),
        }
        return result



policy_service = PolicyService()
