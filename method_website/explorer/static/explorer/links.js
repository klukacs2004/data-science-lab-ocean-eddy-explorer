(() => {
    "use strict";
    const timers = new WeakMap();
    document.addEventListener("click", (event) => {
        const link = event.target.closest?.("a[href]");
        if (!link) return;
        clearTimeout(timers.get(link));
        link.classList.remove("link-click-flash");
        // Restart the brief feedback on repeated clicks without delaying navigation.
        void link.offsetWidth;
        link.classList.add("link-click-flash");
        timers.set(
            link,
            setTimeout(() => {
                link.classList.remove("link-click-flash");
                timers.delete(link);
            }, 260)
        );
    });
})();
