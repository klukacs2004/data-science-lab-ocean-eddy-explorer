(() => {
    "use strict";
    const form = document.getElementById("analysis-form");
    const mode = document.getElementById("id_detection_mode");
    const filtering = document.getElementById("id_filter_mode");
    const candidate = document.getElementById("id_candidate_id");
    const state = document.getElementById("chelton-page-state");
    const clearCandidate = () => {
        if (candidate) candidate.value = "";
    };
    function updateControls() {
        document.querySelectorAll(".single-control").forEach((element) => {
            element.hidden = mode.value === "scan";
            element.querySelectorAll("input, select").forEach((input) => {
                input.disabled = element.hidden;
            });
        });
        const sigma = document.getElementById("sigma-control");
        sigma.hidden = filtering.value !== "custom";
        document.getElementById("id_sigma_cells").disabled = sigma.hidden;
    }
    [mode, filtering].forEach((element) =>
        element.addEventListener("change", () => {
            clearCandidate();
            updateControls();
        })
    );
    updateControls();
    ["id_threshold_cm", "id_polarity", "id_sigma_cells", "id_day", "id_year"].forEach(
        (id) => document.getElementById(id).addEventListener("change", clearCandidate)
    );
    form.addEventListener("submit", () => {
        document.getElementById("run-status").textContent = "Running analysis…";
    });
    const status = document.getElementById("candidate-filter");
    const reason = document.getElementById("reason-filter");
    const polarity = document.getElementById("polarity-filter");
    const rows = [
        ...document.querySelectorAll("#candidate-table tbody tr[data-status]"),
    ];
    function filterRows() {
        let visible = 0;
        rows.forEach((row) => {
            row.hidden =
                (status.value !== "all" && row.dataset.status !== status.value) ||
                (reason.value !== "all" && row.dataset.reason !== reason.value) ||
                (polarity.value !== "all" && row.dataset.polarity !== polarity.value);
            if (!row.hidden) visible++;
        });
        document.getElementById("candidate-count").textContent =
            `Showing ${visible} of ${rows.length} candidates`;
        document.getElementById("filter-empty").hidden =
            visible !== 0 || rows.length === 0;
    }
    if (status) {
        [status, reason, polarity].forEach((element) =>
            element.addEventListener("change", filterRows)
        );
        filterRows();
    }
    document.getElementById("download-candidates")?.addEventListener("click", () => {
        const data = JSON.parse(
            document.getElementById("chelton-candidate-data").textContent
        );
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
        link.download = `chelton_candidates_${state.dataset.date}.csv`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    const map = document.getElementById("chelton-map");
    if (map && typeof map.on === "function")
        map.on("plotly_click", (event) => {
            const id = event.points[0]?.customdata?.[0];
            if (Number.isInteger(id) && candidate) {
                candidate.value = id;
                form.requestSubmit();
            }
        });
    if (state.dataset.selected)
        document.getElementById("inspector").scrollIntoView({ block: "start" });
    const year = document.getElementById("id_year");
    const day = document.getElementById("id_day");
    let controller;
    year.addEventListener("change", async () => {
        controller?.abort();
        controller = new AbortController();
        day.replaceChildren(new Option("Loading dates…", ""));
        day.disabled = true;
        try {
            const url = new URL(state.dataset.datesUrl, window.location.origin);
            url.searchParams.set("year", year.value);
            const response = await fetch(url, { signal: controller.signal });
            if (!response.ok) throw new Error("Dates unavailable");
            const data = await response.json();
            day.replaceChildren(...data.dates.map((date) => new Option(date, date)));
            if (!data.dates.length) day.add(new Option("No dates available", ""));
            day.disabled = false;
        } catch (error) {
            if (error.name === "AbortError") return;
            day.replaceChildren(
                new Option("Could not load dates. Select the year again.", "")
            );
            day.disabled = false;
        }
    });
})();
