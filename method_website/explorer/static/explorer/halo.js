(() => {
    "use strict";
    const form = document.getElementById("analysis-form");
    const year = document.getElementById("id_year");
    const day = document.getElementById("id_day");
    const candidate = document.getElementById("id_candidate_id");
    const state = document.getElementById("halo-page-state");
    form.addEventListener("submit", () => {
        document.getElementById("run-status").textContent = "Running analysis…";
    });
    [
        "id_year",
        "id_day",
        "id_contour_interval_cm",
        "id_max_diameter_km",
        "id_filter_passes",
    ].forEach((id) => {
        document.getElementById(id).addEventListener("change", () => {
            candidate.value = "";
        });
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
        } catch (error) {
            if (error.name === "AbortError") return;
            day.replaceChildren(
                new Option("Could not load dates. Select the year again.", "")
            );
            day.disabled = false;
        }
    });
    document.getElementById("paper-preset")?.addEventListener("click", () => {
        document.getElementById("id_contour_interval_cm").value = 2;
        document.getElementById("id_max_diameter_km").value = 600;
        document.getElementById("id_filter_passes").value = 2;
        if (candidate) candidate.value = "";
    });
    const status = document.getElementById("candidate-filter");
    const reason = document.getElementById("reason-filter");
    const rows = [
        ...document.querySelectorAll("#candidate-table tbody tr[data-status]"),
    ];
    function filterRows() {
        let visible = 0;
        rows.forEach((row) => {
            row.hidden =
                (status.value !== "all" && row.dataset.status !== status.value) ||
                (reason.value !== "all" && row.dataset.reason !== reason.value);
            if (!row.hidden) visible++;
        });
        document.getElementById("candidate-count").textContent =
            `Showing ${visible} of ${rows.length} candidates`;
        document.getElementById("filter-empty").hidden =
            visible !== 0 || rows.length === 0;
    }
    if (status && reason) {
        [status, reason].forEach((control) =>
            control.addEventListener("change", filterRows)
        );
        filterRows();
    }
    document.getElementById("download-candidates")?.addEventListener("click", () => {
        const data = JSON.parse(document.getElementById("halo-candidates").textContent);
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
        link.download = `halo_candidates_${state.dataset.date}.csv`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    const map = document.getElementById("halo-map");
    if (map && typeof map.on === "function")
        map.on("plotly_click", (event) => {
            const id = event.points[0]?.customdata?.[0];
            if (Number.isInteger(id) && candidate) {
                candidate.value = id;
                form.requestSubmit();
            }
        });
    if (state.dataset.selected)
        document.getElementById("inspector")?.scrollIntoView({ block: "start" });
})();
