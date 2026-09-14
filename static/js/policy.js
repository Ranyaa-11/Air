const districtSelect =
    document.getElementById("district-select");

const policySelect =
    document.getElementById("policy-select");

const windowSelect =
    document.getElementById("window-select");

const pollutantDisplay =
    document.getElementById("pollutant-display");

const analyzeButton =
    document.getElementById("analyze-button");

const resultsBody =
    document.getElementById("results-body");

const metricDistrict =
    document.getElementById("metric-district");

const metricPolicy =
    document.getElementById("metric-policy");

const metricImproved =
    document.getElementById("metric-improved");

const metricStatus =
    document.getElementById("metric-status");

const summaryMessage =
    document.getElementById("summary-message");

const insights =
    document.getElementById("insights");

const recommendation =
    document.getElementById("recommendation");


let policyChart = null;


// -----------------------------------
// LOAD DISTRICTS
// -----------------------------------

async function loadDistricts() {

    const response =
        await fetch("/api/policy/districts");

    const data =
        await response.json();


    districtSelect.innerHTML =
        '<option value="">Select District</option>';


    data.districts.forEach(city => {

        const option =
            document.createElement("option");

        option.value = city;
        option.textContent = city;

        districtSelect.appendChild(option);

    });

}


loadDistricts();


// -----------------------------------
// DISTRICT → POLICIES
// -----------------------------------

districtSelect.addEventListener(
    "change",
    async function () {

        const city =
            districtSelect.value;


        policySelect.innerHTML =
            '<option value="">Select Policy</option>';


        pollutantDisplay.textContent =
            "Select a policy to view affected pollutants.";


        if (!city) {

            policySelect.disabled = true;

            return;

        }


        const response =
            await fetch(
                `/api/policy/policies/${encodeURIComponent(city)}`
            );


        const data =
            await response.json();


        data.policies.forEach(policy => {

            const option =
                document.createElement("option");

            option.value = policy;
            option.textContent = policy;

            policySelect.appendChild(option);

        });


        policySelect.disabled = false;

    }
);


// -----------------------------------
// POLICY → POLLUTANTS
// -----------------------------------

policySelect.addEventListener(
    "change",
    async function () {

        const policy =
            policySelect.value;


        if (!policy) {

            pollutantDisplay.textContent =
                "Select a policy to view affected pollutants.";

            return;

        }


        const response =
            await fetch(
                `/api/policy/pollutants/${encodeURIComponent(policy)}`
            );


        const data =
            await response.json();


        pollutantDisplay.textContent =
            data.pollutants.join(", ");

    }
);


// -----------------------------------
// ANALYZE POLICY
// -----------------------------------

analyzeButton.addEventListener(
    "click",
    async function () {

        const city =
            districtSelect.value;

        const policy =
            policySelect.value;

        const window =
            parseInt(windowSelect.value);


        if (!city || !policy) {

            alert(
                "Please select a district and policy."
            );

            return;

        }


        analyzeButton.disabled = true;

        analyzeButton.textContent =
            "Analyzing...";


        try {

            const response =
                await fetch(
                    "/api/policy/analyze",
                    {

                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body: JSON.stringify({

                            city: city,

                            policy: policy,

                            window: window

                        })

                    }
                );


            const data =
                await response.json();


            displayResults(
                data,
                city,
                policy
            );


        }

        catch (error) {

            console.error(error);

            alert(
                "Unable to complete policy analysis."
            );

        }


        analyzeButton.disabled = false;

        analyzeButton.textContent =
            "Analyze Policy";

    }
);


// -----------------------------------
// DISPLAY RESULTS
// -----------------------------------

function displayResults(
    data,
    city,
    policy
) {

    const results =
        data.results;


    metricDistrict.textContent =
        city;

    metricPolicy.textContent =
        policy;

    metricStatus.textContent =
        data.status;


    const improved =
        results.filter(
            row =>
                row["% Change"] < 0
        ).length;


    metricImproved.textContent =
        `${improved}/${results.length}`;


    summaryMessage.textContent =
        data.summary;


    // -------------------------------
    // TABLE
    // -------------------------------

    resultsBody.innerHTML = "";


    results.forEach(row => {

        const tr =
            document.createElement("tr");


        const trend =
            row["% Change"] < 0
                ? "Improved"
                : "Increased";


        tr.innerHTML = `

            <td>
                ${row.Pollutant}
            </td>

            <td>
                ${row.Before ?? "--"}
            </td>

            <td>
                ${row.After ?? "--"}
            </td>

            <td>
                ${row["% Change"] ?? "--"}%
            </td>

            <td>
                ${trend}
            </td>

        `;


        resultsBody.appendChild(tr);

    });


    // -------------------------------
    // INSIGHTS
    // -------------------------------

    const improvedPollutants =
        results
            .filter(
                row =>
                    row["% Change"] < 0
            )
            .map(
                row =>
                    row.Pollutant
            );


    const increasedPollutants =
        results
            .filter(
                row =>
                    row["% Change"] >= 0
            )
            .map(
                row =>
                    row.Pollutant
            );


    let insightHTML = "";


    if (improvedPollutants.length) {

        insightHTML += `
            <p>
                <strong>Improved Pollutants:</strong>
                ${improvedPollutants.join(", ")}
            </p>
        `;

    }


    if (increasedPollutants.length) {

        insightHTML += `
            <p>
                <strong>Increased Pollutants:</strong>
                ${increasedPollutants.join(", ")}
            </p>
        `;

    }


    insights.innerHTML =
        insightHTML;


    // -------------------------------
    // RECOMMENDATION
    // -------------------------------

    if (
        data.status ===
        "Highly Effective"
    ) {

        recommendation.textContent =
            "The selected policy shows strong environmental improvement. Continue implementation and periodic monitoring.";

    }

    else if (
        data.status ===
        "Moderately Effective"
    ) {

        recommendation.textContent =
            "The policy demonstrates moderate effectiveness. Additional interventions and monitoring are recommended.";

    }

    else {

        recommendation.textContent =
            "Limited improvement was observed. Review implementation strategy and strengthen pollution control measures.";

    }


    // -------------------------------
    // CHART
    // -------------------------------

    createChart(results);

}


// -----------------------------------
// CHART
// -----------------------------------

function createChart(results) {

    const canvas =
        document.getElementById(
            "policyChart"
        );


    if (policyChart) {

        policyChart.destroy();

    }


    policyChart =
        new Chart(
            canvas,
            {

                type: "bar",

                data: {

                    labels:
                        results.map(
                            row =>
                                row.Pollutant
                        ),

                    datasets: [

                        {
                            label: "Before",

                            data:
                                results.map(
                                    row =>
                                        row.Before
                                ),

                            borderWidth: 1
                        },

                        {
                            label: "After",

                            data:
                                results.map(
                                    row =>
                                        row.After
                                ),

                            borderWidth: 1
                        }

                    ]

                },

                options: {

                    responsive: true,

                    maintainAspectRatio: false,

                    scales: {

                        y: {

                            beginAtZero: true,

                            title: {

                                display: true,

                                text:
                                    "Average Concentration"

                            }

                        }

                    }

                }

            }
        );

}