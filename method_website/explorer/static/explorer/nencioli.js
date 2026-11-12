(() => {
    "use strict";
    const form = document.getElementById("analysis-form");
    const mode = document.getElementById("id_detection_mode");
    const state = document.getElementById("nencioli-page-state");
    const candidate = document.getElementById("id_candidate_id");
    function updateMode() {
        const sweep = mode.value === "sweep";
        for (const [selector, hidden] of [
            [".single-control", sweep],
            [".range-control", !sweep],
        ]) {
            document.querySelectorAll(selector).forEach((element) => {
                element.hidden = hidden;
                element.querySelectorAll("input").forEach((input) => {
                    input.disabled = hidden;
                });
            });
        }
        if (candidate) candidate.disabled = sweep;
    }
    mode.addEventListener("change", () => {
        if (candidate) candidate.value = "";
        updateMode();
    });
    updateMode();
    document.querySelectorAll("[data-parameters]").forEach((button) => {
        button.addEventListener("click", () => {
            const [a, b] = button.dataset.parameters.split(",");
            mode.value = "single";
            document.getElementById("id_a").value = a;
            document.getElementById("id_b").value = b;
            if (candidate) candidate.value = "";
            updateMode();
        });
    });
    ["id_a", "id_b", "id_day", "id_year"].forEach((id) => {
        document.getElementById(id).addEventListener("change", () => {
            if (candidate) candidate.value = "";
        });
    });
    form.addEventListener("submit", () => {
        document.getElementById("run-status").textContent = "Running analysis…";
    });
    const status = document.getElementById("candidate-filter");
    const reason = document.getElementById("reason-filter");
    const rows = [
        ...document.querySelectorAll("#candidate-table tbody tr[data-status]"),
    ];
    function filterCandidates() {
        let visible = 0;
        rows.forEach((row) => {
            row.hidden =
                (status.value !== "all" && row.dataset.status !== status.value) ||
                (reason.value !== "all" && row.dataset.reason !== reason.value);
            if (!row.hidden) visible++;
        });
        document.getElementById("candidate-count").textContent =
            `Showing ${visible} of ${rows.length} candidate searches`;
        document.getElementById("filter-empty").hidden =
            visible !== 0 || rows.length === 0;
    }
    if (status && reason) {
        status.addEventListener("change", filterCandidates);
        reason.addEventListener("change", filterCandidates);
        filterCandidates();
    }
    function csvDownload(dataId, filename) {
        const data = JSON.parse(document.getElementById(dataId).textContent);
        if (!data.length) return;
        const keys = Object.keys(data[0]);
        const escape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
        const csv = [keys, ...data.map((row) => keys.map((key) => row[key]))]
            .map((row) => row.map(escape).join(","))
            .join("\r\n");
        const url = URL.createObjectURL(
            new Blob([csv], { type: "text/csv;charset=utf-8" })
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    document
        .getElementById("download-candidates")
        ?.addEventListener("click", () =>
            csvDownload(
                "nencioli-candidate-data",
                `nencioli_candidates_${state.dataset.date}.csv`
            )
        );
    document
        .getElementById("download-sweep")
        ?.addEventListener("click", () =>
            csvDownload(
                "nencioli-sweep-data",
                `nencioli_sweep_${state.dataset.date}.csv`
            )
        );
    const map = document.getElementById("nencioli-map");
    if (map && typeof map.on === "function")
        map.on("plotly_click", (event) => {
            const id = event.points[0]?.customdata?.[0];
            if (Number.isInteger(id) && candidate) {
                candidate.value = id;
                form.requestSubmit();
            }
        });
    const sweep = document.getElementById("nencioli-sweep");
    if (sweep && typeof sweep.on === "function")
        sweep.on("plotly_click", (event) => {
            const point = event.points[0];
            const submitter = document.createElement("button");
            submitter.type = "submit";
            submitter.name = "inspect_configuration";
            submitter.value = `${point.x},${point.y}`;
            submitter.hidden = true;
            form.appendChild(submitter);
            form.requestSubmit(submitter);
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
