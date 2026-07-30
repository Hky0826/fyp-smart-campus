const { useEffect, useRef } = React;

function Icon({ name, className = "" }) {
    const ref = useRef(null);
    useEffect(() => {
        if (ref.current && window.lucide) {
            const allowedNames = new Set([
                "alert-circle", "check-circle", "x", "search", "plus", "chevron-up",
                "chevron-down", "chevrons-up-down", "chevron-left", "chevron-right",
                "chevrons-left", "chevrons-right", "circle-help", "user", "settings",
            ]);
            const safeName = allowedNames.has(name) ? name : "circle-help";
            const safeClass = String(className).split(/\s+/).filter(token => /^[A-Za-z0-9:_/-]+$/.test(token)).join(" ");
            const icon = document.createElement("i");
            icon.setAttribute("data-lucide", safeName);
            icon.setAttribute("class", safeClass);
            ref.current.replaceChildren(icon);
            window.lucide.createIcons({
                node: ref.current
            });
        }
    }, [name, className]);

    return <span ref={ref} className="inline-flex items-center justify-center" />;
}

window.Icon = Icon;
