(() => {
    "use strict";
    const form = document.getElementById("analysis-form");
    const state = document.getElementById("comparison-state");
    const year = document.getElementById("id_year");
    const day = document.getElementById("id_day");
    const mode = document.getElementById("id_filter_mode");
    const sigma = document.getElementById("id_sigma_cells");
    function updateControls() {
        document.getElementById("sigma-control").hidden = mode.value !== "custom";
        sigma.disabled = mode.value !== "custom";
    }
    mode.addEventListener("change", updateControls);
    updateControls();
    document.querySelectorAll("[data-parameters]").forEach((button) =>
        button.addEventListener("click", () => {
            const [a, b] = button.dataset.parameters.split(",");
            document.getElementById("id_a").value = a;
            document.getElementById("id_b").value = b;
        })
    );
    form.addEventListener("submit", () => {
        document.getElementById("run-status").textContent =
            "Running all three methods…";
    });
    const comparisonMode = document.getElementById("comparison-mode");
    const duration = document.getElementById("id_duration_days");
    function updatePeriod() {
        const output = document.getElementById("comparison-period");
        const days = Number(duration.value);
        if (
            !day.value ||
            !duration.validity.valid ||
            !Number.isInteger(days) ||
            days < 1
        ) {
            output.textContent =
                "Choose a start date and a duration from 1 to 365 days.";
            return;
        }
        const end = new Date(`${day.value}T00:00:00Z`);
        end.setUTCDate(end.getUTCDate() + days - 1);
        output.textContent = `${day.value} → ${end.toISOString().slice(0, 10)} · ${days} consecutive days, including the start date. All daily grids must be available.`;
    }
    function setText(id, text) {
        const element = document.getElementById(id);
        if (element) element.textContent = text;
    }
    function updateComparisonMode() {
        const tracking = comparisonMode.value === "tracking";
        const controls = document.getElementById("comparison-tracking-controls");
        controls.hidden = !tracking;
        controls.querySelectorAll("input").forEach((input) => {
            input.disabled = !tracking;
        });
        document.querySelector('label[for="id_day"]').textContent = tracking
            ? "Tracking start date"
            : "Available date";
        form.querySelector('button[type="submit"]').textContent = tracking
            ? "Compare tracking over this period"
            : "Compare daily detections";
        setText(
            "comparison-page-title",
            tracking
                ? "Compare eddy tracking methods"
                : "Compare eddy detection methods"
        );
        setText(
            "comparison-introduction",
            tracking
                ? "Track Chelton, Nencioli, and Halo eddies over the same period. Compare observed spans and sizes, then inspect radius evolution within the same span classes."
                : "Run all three methods on the same daily grid. Compare their boundaries, match detections between methods, and inspect counts and contour-based sizes."
        );
        setText(
            "comparison-input-description",
            tracking
                ? "One start date and period for all methods."
                : "One date and daily grid for all methods."
        );
        setText(
            "comparison-output-description",
            tracking
                ? "Size and span distributions, then radius evolution."
                : "Boundaries, geometric matches, counts, and sizes."
        );
        setText(
            "comparison-empty-title",
            tracking
                ? "One period, three tracking methods"
                : "One day, three detection methods"
        );
        setText(
            "comparison-empty-description",
            tracking
                ? "Choose an available start date and up to 365 days. Run the comparison to see span and size distributions and radius evolution. Short periods may have no complete tracks in the longer span classes."
                : "Choose a date and run the comparison to inspect accepted boundaries, geometric matches, counts, and sizes."
        );
        updatePeriod();
    }
    duration.addEventListener("input", updatePeriod);
    day.addEventListener("change", updatePeriod);
    comparisonMode.addEventListener("change", updateComparisonMode);
    updateComparisonMode();
    form.addEventListener("submit", () => {
        if (comparisonMode.value === "tracking")
            document.getElementById("run-status").textContent =
                "Running detection and tracking for all three methods over the selected period…";
    });
    const jobPanel = document.getElementById("comparison-job");
    if (jobPanel && ["queued", "running"].includes(jobPanel.dataset.status)) {
        let retries = 0;
        async function pollJob() {
            try {
                const response = await fetch(jobPanel.dataset.statusUrl, {
                    cache: "no-store",
                    signal: AbortSignal.timeout(15000),
                });
                if (!response.ok) throw new Error("Progress unavailable");
                const job = await response.json();
                retries = 0;
                setText("comparison-job-message", job.message);
                setText(
                    "comparison-job-cache",
                    `Daily detection results reused: ${job.cache_hits}`
                );
                const bar = document.getElementById("comparison-job-progress");
                bar.max = job.total;
                bar.value = job.completed;
                if (["succeeded", "failed"].includes(job.status)) {
                    window.location.reload();
                    return;
                }
            } catch (error) {
                retries++;
                setText(
                    "comparison-job-message",
                    "Connection interrupted. Reconnecting to your run… You can also refresh this page."
                );
            }
            setTimeout(pollJob, Math.min(15000, 1500 * (1 + retries)));
        }
        setTimeout(pollJob, 500);
    }
    form.addEventListener("submit", () => {
        if (comparisonMode.value === "tracking") {
            const button = form.querySelector('button[type="submit"]');
            button.disabled = true;
            setText("run-status", "Opening your background comparison…");
        }
    });
    let controller;
    year.addEventListener("change", async () => {
        controller?.abort();
        controller = new AbortController();
        day.disabled = true;
        day.replaceChildren(new Option("Loading dates…", ""));
        try {
            const url = new URL(state.dataset.datesUrl, window.location.origin);
            url.searchParams.set("year", year.value);
            const response = await fetch(url, { signal: controller.signal });
            if (!response.ok) throw new Error("Dates unavailable");
            const data = await response.json();
            day.replaceChildren(...data.dates.map((date) => new Option(date, date)));
            if (!data.dates.length) day.add(new Option("No dates available", ""));
            day.disabled = false;
            updatePeriod();
        } catch (error) {
            if (error.name === "AbortError") return;
            day.replaceChildren(
                new Option("Could not load dates. Select the year again.", "")
            );
            day.disabled = false;
        }
    });
    const method = document.getElementById("method-filter");
    const polarity = document.getElementById("polarity-filter");
    const rows = [
        ...document.querySelectorAll("#comparison-table tbody tr[data-method]"),
    ];
    function filterRows() {
        let visible = 0;
        rows.forEach((row) => {
            row.hidden =
                (method.value !== "all" && row.dataset.method !== method.value) ||
                (polarity.value !== "all" && row.dataset.polarity !== polarity.value);
            if (!row.hidden) visible++;
        });
        document.getElementById("detection-count").textContent =
            `Showing ${visible} of ${rows.length} detections`;
        document.getElementById("filter-empty").hidden =
            visible !== 0 || rows.length === 0;
    }
    if (method && polarity) {
        [method, polarity].forEach((control) =>
            control.addEventListener("change", filterRows)
        );
        filterRows();
    }
    function assignMatches(candidates) {
        const usedByMethodPair = new Map();
        return [...candidates]
            .sort(
                (a, b) => b.iou - a.iou || a.center_distance_km - b.center_distance_km
            )
            .filter((pair) => {
                const methodPair = JSON.stringify(
                    [pair.method_a, pair.method_b].sort()
                );
                if (!usedByMethodPair.has(methodPair))
                    usedByMethodPair.set(methodPair, new Set());
                const used = usedByMethodPair.get(methodPair);
                const a = JSON.stringify([pair.method_a, pair.id_a]);
                const b = JSON.stringify([pair.method_b, pair.id_b]);
                if (used.has(a) || used.has(b)) return false;
                used.add(a);
                used.add(b);
                return true;
            });
    }
    const matchingData = document.getElementById("matching-data");
    if (matchingData) {
        const pairs = JSON.parse(matchingData.textContent);
        const controls = [
            "match-methods",
            "match-distance",
            "match-iou",
            "match-unknown",
        ].map((id) => document.getElementById(id));
        let selected = [];
        function updateMatches() {
            const [methods, distance, overlap, includeUnknown] = controls;
            const valid =
                distance.validity.valid &&
                overlap.validity.valid &&
                distance.value.trim() !== "" &&
                overlap.value.trim() !== "";
            const methodCandidates = pairs.filter(
                (pair) =>
                    methods.value === "all" ||
                    methods.value === `${pair.method_a},${pair.method_b}` ||
                    methods.value === `${pair.method_b},${pair.method_a}`
            );
            const thresholdCandidates = valid
                ? methodCandidates.filter(
                      (pair) =>
                          pair.iou !== null &&
                          pair.center_distance_km <= Number(distance.value) &&
                          pair.iou >= Number(overlap.value)
                  )
                : [];
            const eligible = thresholdCandidates.filter(
                (pair) =>
                    pair.polarity_check === "agrees" ||
                    (includeUnknown.checked && pair.polarity_check === "unresolved")
            );
            selected = assignMatches(eligible);
            const body = document.querySelector("#match-table tbody");
            body.replaceChildren();
            selected.forEach((pair) => {
                const row = document.createElement("tr");
                ["a", "b"].forEach((side) => {
                    const cell = row.insertCell();
                    const link = document.createElement("a");
                    link.href = `#detection-${pair[`method_${side}`]}-${pair[`id_${side}`]}`;
                    link.textContent = `${pair[`label_${side}`]} · ${pair[`id_${side}`]}`;
                    link.addEventListener("click", () => {
                        method.value = "all";
                        polarity.value = "all";
                        filterRows();
                        rows.forEach((item) =>
                            item.classList.toggle(
                                "selected",
                                item.id === link.hash.slice(1)
                            )
                        );
                    });
                    cell.append(link);
                });
                row.insertCell().textContent = pair.center_distance_km.toFixed(2);
                row.insertCell().textContent = pair.iou.toFixed(3);
                row.insertCell().textContent = `${pair.polarity_a} / ${pair.polarity_b}`;
                row.insertCell().textContent =
                    pair.polarity_check === "agrees" ? "Agrees" : "Unresolved";
                body.append(row);
            });
            if (!selected.length) {
                const cell = body.insertRow().insertCell();
                cell.colSpan = 6;
                cell.className = "empty-table-cell";
                cell.textContent = valid
                    ? "No pairs meet the current matching settings."
                    : "Enter valid matching thresholds.";
            }
            const unresolved = selected.filter(
                (pair) => pair.polarity_check === "unresolved"
            ).length;
            document.getElementById("match-count").textContent = valid
                ? `Total cross-method candidates: ${pairs.length}. In selected method pair(s): ${methodCandidates.length}. Passing both thresholds: ${thresholdCandidates.length}. Passing polarity settings: ${eligible.length}. Matched pairs: ${selected.length} (${selected.length - unresolved} with agreeing polarities; ${unresolved} unresolved).${thresholdCandidates.length ? (eligible.length ? "" : " No pairs pass the polarity settings.") : " No pairs meet both thresholds."}`
                : "Enter a nonnegative distance and an IoU between 0 and 1.";
            document.getElementById("download-matches").disabled = !selected.length;
        }
        controls.forEach((control) =>
            control.addEventListener("change", updateMatches)
        );
        document.getElementById("download-matches").addEventListener("click", () => {
            if (!selected.length) return;
            const keys = Object.keys(selected[0]);
            const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
            const csv = [keys, ...selected.map((pair) => keys.map((key) => pair[key]))]
                .map((row) => row.map(quote).join(","))
                .join("\r\n");
            const url = URL.createObjectURL(
                new Blob([csv], { type: "text/csv;charset=utf-8" })
            );
            const link = document.createElement("a");
            link.href = url;
            link.download = `eddy_matches_${state.dataset.date}.csv`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        });
        updateMatches();
    }
    const map = document.getElementById("comparison-map");
    document.getElementById("download-detection-map")?.addEventListener("click", () => {
        Plotly.downloadImage(map, {
            format: "png",
            filename: `eddy_comparison_${state.dataset.date}`,
            scale: 2,
        });
    });
    if (map && typeof map.on === "function")
        map.on("plotly_click", (event) => {
            const data = event.points[0]?.customdata;
            if (!Array.isArray(data) || !Number.isInteger(data[1])) return;
            const row = document.getElementById(`detection-${data[0]}-${data[1]}`);
            if (!row) return;
            method.value = "all";
            polarity.value = "all";
            filterRows();
            rows.forEach((item) => item.classList.remove("selected"));
            row.classList.add("selected");
            row.scrollIntoView({ block: "center", behavior: "smooth" });
        });
    document.getElementById("download-statistics")?.addEventListener("click", () => {
        const summary = JSON.parse(
            document.getElementById("comparison-summary-data").textContent
        );
        const keys = [
            "label",
            "count",
            "cyclonic",
            "anticyclonic",
            "unknown",
            "mean_radius_km",
            "median_radius_km",
            "min_radius_km",
            "max_radius_km",
            "mean_area_km2",
        ];
        const headers = [
            "Method",
            "Count",
            "Cyclonic",
            "Anticyclonic",
            "Unknown",
            "Mean radius [km]",
            "Median radius [km]",
            "Minimum radius [km]",
            "Maximum radius [km]",
            "Mean area [km²]",
        ];
        const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
        const csv = [headers, ...summary.map((item) => keys.map((key) => item[key]))]
            .map((row) => row.map(quote).join(","))
            .join("\r\n");
        const url = URL.createObjectURL(
            new Blob([csv], { type: "text/csv;charset=utf-8" })
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = `eddy_basic_statistics_${state.dataset.date}.csv`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    document.getElementById("download-comparison")?.addEventListener("click", () => {
        const data = JSON.parse(document.getElementById("comparison-data").textContent);
        if (!data.length) return;
        const keys = Object.keys(data[0]);
        const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
        const csv = [keys, ...data.map((row) => keys.map((key) => row[key]))]
            .map((row) => row.map(quote).join(","))
            .join("\r\n");
        const url = URL.createObjectURL(
            new Blob([csv], { type: "text/csv;charset=utf-8" })
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = `eddy_comparison_${state.dataset.date}.csv`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
})();
