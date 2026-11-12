(() => {
    "use strict";
    const form = document.getElementById("analysis-form");
    const submit = form.querySelector('button[type="submit"]');
    const status = document.getElementById("run-status");
    const year = document.getElementById("id_year");
    const day = document.getElementById("id_day");
    const filterMode = document.getElementById("id_filter_mode");
    if (filterMode) {
        const sigma = document.getElementById("id_sigma_cells");
        const sigmaControl = document.getElementById("tracking-sigma-control");
        function updateFiltering() {
            sigmaControl.hidden = filterMode.value !== "custom";
            sigma.disabled = filterMode.value !== "custom";
        }
        filterMode.addEventListener("change", updateFiltering);
        updateFiltering();
    }
    let running = false;
    let loadingDates = false;
    form.addEventListener("submit", (event) => {
        if (running || loadingDates || !day.value) {
            event.preventDefault();
            return;
        }
        running = true;
        submit.disabled = true;
        form.setAttribute("aria-busy", "true");
        status.textContent =
            "Running daily detection and tracking… Please keep this page open.";
    });
    window.addEventListener("pageshow", () => {
        running = false;
        submit.disabled = loadingDates;
        form.removeAttribute("aria-busy");
        status.textContent = "";
    });
    let controller;
    year.addEventListener("change", async () => {
        controller?.abort();
        controller = new AbortController();
        loadingDates = true;
        submit.disabled = true;
        day.disabled = true;
        day.replaceChildren(new Option("Loading dates…", ""));
        try {
            const url = new URL(
                document.getElementById("tracking-state").dataset.datesUrl,
                window.location.origin
            );
            url.searchParams.set("year", year.value);
            const response = await fetch(url, { signal: controller.signal });
            if (!response.ok) throw new Error("Dates unavailable");
            const data = await response.json();
            day.replaceChildren(...data.dates.map((value) => new Option(value, value)));
            if (!data.dates.length) day.add(new Option("No dates available", ""));
        } catch (error) {
            if (error.name === "AbortError") return;
            day.replaceChildren(
                new Option("Could not load dates. Select the year again.", "")
            );
        }
        loadingDates = false;
        day.disabled = false;
        submit.disabled = running || !day.value;
    });
    const map = document.getElementById("tracking-map");
    const selector = document.getElementById("track-selector");
    function showObservations(id) {
        const plot = document.getElementById("track-observations");
        const message = document.getElementById("observation-status");
        if (!plot || !message) return;
        const trace = map.data.find(
            (item) =>
                String(item.meta?.track_id) === id && item.mode.includes("markers")
        );
        plot.hidden = !trace;
        if (!trace) {
            message.textContent =
                "Select a track on the main plot, in the selector, or in the table to inspect every observation date.";
            return;
        }
        const radians = (value) => (value * Math.PI) / 180;
        const distances = trace.lon.map((longitude, index) => {
            const latitude = trace.lat[index];
            const a =
                Math.sin(radians(latitude - trace.lat[0]) / 2) ** 2 +
                Math.cos(radians(latitude)) *
                    Math.cos(radians(trace.lat[0])) *
                    Math.sin(radians(longitude - trace.lon[0]) / 2) ** 2;
            return 6371 * 2 * Math.asin(Math.sqrt(Math.max(0, Math.min(1, a))));
        });
        message.textContent = `Track ${id}: ${trace.lon.length} dated observations. Hover to inspect centers and repeat counts.`;
        const maxDistance = Math.max(0, ...distances);
        window.Plotly.react(
            plot,
            [
                {
                    x: trace.customdata.map((row) => row[1]),
                    y: distances,
                    mode: "lines+markers",
                    marker: trace.marker,
                    customdata: trace.customdata.map((row, index) => [
                        ...row.slice(0, 5),
                        trace.lat[index],
                        trace.lon[index],
                        row[5] ?? null,
                    ]),
                    hovertemplate:
                        "Track %{customdata[0]} · %{x|%Y-%m-%d}<br>" +
                        "%{customdata[5]:.3f}°N, %{customdata[6]:.3f}°E<br>" +
                        "Distance from first center: %{y:.2f} km<br>Radius: %{customdata[2]:.2f} km<br>" +
                        "%{customdata[3]}<br>Observations at this exact center: %{customdata[4]}" +
                        (trace.customdata[0]?.length > 5
                            ? "<br>Mean relative vorticity: %{customdata[7]:.3e} s⁻¹"
                            : "") +
                        "<extra></extra>",
                },
            ],
            {
                height: 330,
                margin: { l: 65, r: 25, t: 20, b: 65 },
                showlegend: false,
                paper_bgcolor: "rgba(0,0,0,0)",
                plot_bgcolor: "rgba(0,0,0,0)",
                font: map.layout.font,
                hoverlabel: map.layout.hoverlabel,
                xaxis: {
                    title: { text: "Observation date" },
                    type: "date",
                    tickformat: "%Y-%m-%d",
                    gridcolor: "rgba(49,78,95,0.18)",
                },
                yaxis: {
                    title: { text: "Distance from first center [km]" },
                    range: [0, Math.max(1, maxDistance * 1.1)],
                    gridcolor: "rgba(49,78,95,0.18)",
                },
            },
            { responsive: true, displaylogo: false }
        );
    }
    function selectTrack(id) {
        if (!map || !selector || !window.Plotly) return;
        selector.value = id;
        const visible = map.data.map((trace) =>
            trace.meta?.kind === "dataset_grid"
                ? id === "all"
                    ? (trace.visible ?? true)
                    : true
                : id === "all" || String(trace.meta?.track_id) === id
        );
        const bounds = { lon: [], lat: [] };
        map.data.forEach((trace, index) => {
            if (visible[index] !== true || trace.meta?.kind === "dataset_grid") return;
            for (const axis of ["lon", "lat"]) {
                for (const value of trace[axis] ?? []) {
                    if (Number.isFinite(value)) bounds[axis].push(value);
                }
            }
        });
        const layout = {};
        if (bounds.lon.length && bounds.lat.length) {
            const west = Math.min(...bounds.lon),
                east = Math.max(...bounds.lon);
            const south = Math.min(...bounds.lat),
                north = Math.max(...bounds.lat);
            const mercator = (latitude) =>
                Math.log(
                    Math.tan(
                        Math.PI / 4 +
                            (Math.max(-85, Math.min(85, latitude)) * Math.PI) / 360
                    )
                );
            const width = map.clientWidth || 800;
            const height = Math.max(200, (map.clientHeight || 620) - 85);
            // Include nearby grid centers even when a track stays at one location.
            const grid = map.data.find((trace) => trace.meta?.kind === "dataset_grid");
            function gridStep(values) {
                const coordinates = [...new Set(values ?? [])]
                    .filter(Number.isFinite)
                    .sort((a, b) => a - b);
                let step = Infinity;
                for (let i = 1; i < coordinates.length; i++)
                    step = Math.min(step, coordinates[i] - coordinates[i - 1]);
                return Number.isFinite(step) ? step : 0;
            }
            const latitude = (south + north) / 2;
            const lonSpan = Math.max(
                (east - west) / 360,
                (3 * gridStep(grid?.lon)) / 360,
                0.0002
            );
            const latPadding = 1.5 * gridStep(grid?.lat);
            const latSpan = Math.max(
                (mercator(north) - mercator(south)) / (2 * Math.PI),
                (mercator(latitude + latPadding) - mercator(latitude - latPadding)) /
                    (2 * Math.PI),
                0.0002
            );
            layout["map.center"] = {
                lon: (west + east) / 2,
                lat:
                    ((2 * Math.atan(Math.exp((mercator(north) + mercator(south)) / 2)) -
                        Math.PI / 2) *
                        180) /
                    Math.PI,
            };
            layout["map.zoom"] = Math.max(
                0,
                Math.min(
                    12,
                    Math.log2(
                        Math.min(
                            width / (512 * lonSpan * 1.3),
                            height / (512 * latSpan * 1.3)
                        )
                    )
                )
            );
        }
        window.Plotly.update(map, { visible }, layout);
        showObservations(id);
        document.querySelectorAll("#track-table tr[data-track-id]").forEach((row) => {
            row.classList.toggle("selected", row.dataset.trackId === id);
        });
    }
    selector?.addEventListener("change", () => selectTrack(selector.value));
    document.querySelectorAll("[data-inspect-track]").forEach((button) =>
        button.addEventListener("click", () => {
            selectTrack(button.dataset.inspectTrack);
            document
                .getElementById("trajectories")
                .scrollIntoView({ block: "start", behavior: "smooth" });
        })
    );
    if (map && typeof map.on === "function")
        map.on("plotly_click", (event) => {
            const point = event.points[0];
            const id = point?.customdata?.[0] ?? point?.data?.meta?.track_id;
            if (!Number.isInteger(id)) return;
            selectTrack(String(id));
        });
})();
