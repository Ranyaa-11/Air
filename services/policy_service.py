import pandas as pd


# Load project data

policy_df = pd.read_excel("Policy.xlsx")
pollution_df = pd.read_excel("Disdata_Cleaned.xlsx")
district_policy_df = pd.read_excel("DistrictPolicy.xlsx")


# Fix pollutant naming

policy_df["Affected_Pollutants"] = (
    policy_df["Affected_Pollutants"]
    .str.replace("O3", "Ozone")
)


def get_districts():

    return sorted(
        district_policy_df["District"]
        .dropna()
        .unique()
        .tolist()
    )


def get_policies_for_district(city):

    policies = district_policy_df[
        district_policy_df["District"] == city
    ]["Policy"].tolist()

    return policies


def get_policy_pollutants(policy):

    policy_row = policy_df[
        policy_df["Policy_Name"] == policy
    ]

    if policy_row.empty:
        return []

    pollutants = (
        policy_row["Affected_Pollutants"]
        .iloc[0]
        .split(",")
    )

    return [p.strip() for p in pollutants]


def analyze_policy(city, policy, window=3):

    # Get policy details

    policy_row = policy_df[
        policy_df["Policy_Name"] == policy
    ]

    if policy_row.empty:
        raise ValueError("Policy not found.")


    policy_date = pd.to_datetime(
        policy_row["Start_Date"].iloc[0],
        dayfirst=True
    )


    pollutants = get_policy_pollutants(policy)


    # Filter district

    city_df = pollution_df[
        pollution_df["City"] == city
    ].copy()


    city_df["Date"] = pd.to_datetime(
        city_df["Date"]
    )


    # Before / After window

    before_start = (
        policy_date -
        pd.DateOffset(months=window)
    )

    after_end = (
        policy_date +
        pd.DateOffset(months=window)
    )


    before_df = city_df[
        (city_df["Date"] >= before_start) &
        (city_df["Date"] < policy_date)
    ]


    after_df = city_df[
        (city_df["Date"] >= policy_date) &
        (city_df["Date"] <= after_end)
    ]


    # Calculate results

    results = []


    for pollutant in pollutants:

        pollutant = pollutant.strip()

        if pollutant not in city_df.columns:
            continue

        avg_before = before_df[pollutant].mean()

        avg_after = after_df[pollutant].mean()


        if pd.isna(avg_before) or avg_before == 0:
            change = None

        else:

            change = (
                (avg_after - avg_before)
                / avg_before
            ) * 100


        results.append({

            "Pollutant": pollutant,

            "Before": (
                round(avg_before, 2)
                if not pd.isna(avg_before)
                else None
            ),

            "After": (
                round(avg_after, 2)
                if not pd.isna(avg_after)
                else None
            ),

            "% Change": (
                round(change, 2)
                if change is not None
                else None
            )

        })


    results_df = pd.DataFrame(results)


    # Effectiveness

    if not results_df.empty:

        improved = (
            results_df["% Change"] < 0
        ).sum()

        total = len(results_df)

    else:

        improved = 0
        total = 0


    effectiveness = (
        (improved / total) * 100
        if total > 0
        else 0
    )


    if effectiveness >= 70:

        status = "Highly Effective"

    elif effectiveness >= 40:

        status = "Moderately Effective"

    else:

        status = "Low Impact"


    # Summary

    summary = (
        f"{policy} was analyzed using "
        f"a {window}-month before/after window.\n\n"
        f"Improved {improved} out of "
        f"{total} pollutants.\n"
        f"Overall Impact: {status}"
    )


    return {

        "results": results_df.to_dict(
            orient="records"
        ),

        "effectiveness": round(
            effectiveness, 2
        ),

        "status": status,

        "summary": summary,

        "pollutants": pollutants,

        "policy_date":
            policy_date.strftime("%Y-%m-%d")

    }