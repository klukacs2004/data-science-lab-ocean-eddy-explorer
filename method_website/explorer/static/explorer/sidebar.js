(() => {
    "use strict";
    const app = document.querySelector(".app");
    const sidebar = document.getElementById("explorer-sidebar");
    const handle = app?.querySelector(".sidebar-resizer");
    if (!app || !sidebar || !handle) return;

    const storageKey = "eddy-explorer-sidebar-width";
    const mobile = window.matchMedia("(max-width: 680px)");
    const minWidth = 240;
    let preferredWidth = null;
    let drag = null;
    let resizeFrame = null;
    try {
        const stored = window.localStorage.getItem(storageKey);
        const width = Number(stored);
        if (
            stored !== null &&
            Number.isFinite(width) &&
            width >= minWidth &&
            width <= 600
        )
            preferredWidth = width;
    } catch {
        /* Resizing still works when browser storage is unavailable. */
    }

    const maxWidth = () =>
        Math.max(minWidth, Math.min(600, app.getBoundingClientRect().width - 360));
    const clamp = (width) =>
        Math.round(Math.max(minWidth, Math.min(maxWidth(), width)));
    function resizePlots() {
        if (resizeFrame !== null) return;
        resizeFrame = window.requestAnimationFrame(() => {
            resizeFrame = null;
            if (!window.Plotly?.Plots?.resize) return;
            app.querySelectorAll(".workspace .js-plotly-plot").forEach((plot) => {
                if (!plot._fullLayout || !plot.clientWidth || !plot.clientHeight)
                    return;
                window.Plotly.Plots.resize(plot);
            });
        });
    }
    function applyWidth() {
        if (mobile.matches) {
            app.style.removeProperty("--sidebar-width");
            handle.tabIndex = -1;
            handle.setAttribute("aria-disabled", "true");
        } else {
            const width = clamp(
                preferredWidth ?? (window.innerWidth <= 900 ? 240 : 350)
            );
            app.style.setProperty("--sidebar-width", `${width}px`);
            handle.tabIndex = 0;
            handle.setAttribute("aria-disabled", "false");
            handle.setAttribute("aria-valuemax", String(Math.floor(maxWidth())));
            handle.setAttribute("aria-valuenow", String(width));
            handle.setAttribute("aria-valuetext", `${width} pixels`);
        }
        resizePlots();
    }
    function remember() {
        try {
            if (preferredWidth === null) window.localStorage.removeItem(storageKey);
            else window.localStorage.setItem(storageKey, String(preferredWidth));
        } catch {
            /* Optional persistence must not prevent resizing. */
        }
    }
    function stopDrag(event) {
        if (
            !drag ||
            (event?.pointerId !== undefined && event.pointerId !== drag.pointerId)
        )
            return;
        const pointerId = drag.pointerId;
        drag = null;
        app.classList.remove("sidebar-resizing");
        document.body.classList.remove("sidebar-resizing");
        if (handle.hasPointerCapture(pointerId))
            handle.releasePointerCapture(pointerId);
        remember();
        resizePlots();
    }
    handle.addEventListener("pointerdown", (event) => {
        if (mobile.matches || event.button !== 0 || drag) return;
        event.preventDefault();
        handle.focus();
        drag = {
            pointerId: event.pointerId,
            x: event.clientX,
            width: sidebar.getBoundingClientRect().width,
        };
        handle.setPointerCapture(event.pointerId);
        app.classList.add("sidebar-resizing");
        document.body.classList.add("sidebar-resizing");
    });
    handle.addEventListener("pointermove", (event) => {
        if (!drag || event.pointerId !== drag.pointerId) return;
        preferredWidth = clamp(drag.width + event.clientX - drag.x);
        applyWidth();
    });
    ["pointerup", "pointercancel", "lostpointercapture"].forEach((type) =>
        handle.addEventListener(type, stopDrag)
    );
    handle.addEventListener("dblclick", () => {
        preferredWidth = null;
        remember();
        applyWidth();
    });
    handle.addEventListener("keydown", (event) => {
        if (mobile.matches) return;
        const current = sidebar.getBoundingClientRect().width;
        const step = event.shiftKey ? 50 : 10;
        if (event.key === "ArrowLeft") preferredWidth = clamp(current - step);
        else if (event.key === "ArrowRight") preferredWidth = clamp(current + step);
        else if (event.key === "Home") preferredWidth = minWidth;
        else if (event.key === "End") preferredWidth = maxWidth();
        else if (event.key === "Enter") preferredWidth = null;
        else return;
        event.preventDefault();
        remember();
        applyWidth();
    });
    window.addEventListener("resize", () => {
        if (mobile.matches) stopDrag();
        applyWidth();
    });
    applyWidth();
})();
