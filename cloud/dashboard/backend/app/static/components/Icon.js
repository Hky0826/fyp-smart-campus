const { useEffect, useRef } = React;

function Icon({ name, className = "" }) {
    const ref = useRef(null);
    useEffect(() => {
        if (!ref.current) return;

        const safeName = /^[A-Za-z0-9-]+$/.test(String(name || "")) ? name : "circle-help";
        const safeClass = String(className)
            .split(/\s+/)
            .filter(token => /^[A-Za-z0-9:_/-]+$/.test(token))
            .join(" ");
        const icon = document.createElement("i");
        icon.setAttribute("data-lucide", safeName);
        icon.setAttribute("class", safeClass);
        icon.setAttribute("aria-hidden", "true");
        ref.current.replaceChildren(icon);

        // lucide 0.321 scans the document; it does not support the old
        // {node: ...} option. The fallback keeps controls visible if the
        // optional icon asset is unavailable during a cold load.
        if (window.lucide && typeof window.lucide.createIcons === "function") {
            window.lucide.createIcons();
        }
        if (!ref.current.querySelector("svg")) {
            const fallback = document.createElementNS("http://www.w3.org/2000/svg", "svg");
            fallback.setAttribute("viewBox", "0 0 24 24");
            fallback.setAttribute("fill", "none");
            fallback.setAttribute("stroke", "currentColor");
            fallback.setAttribute("stroke-width", "2");
            fallback.setAttribute("aria-hidden", "true");
            const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            circle.setAttribute("cx", "12");
            circle.setAttribute("cy", "12");
            circle.setAttribute("r", "8");
            fallback.appendChild(circle);
            ref.current.replaceChildren(fallback);
        }
    }, [name, className]);

    return <span ref={ref} className="inline-flex items-center justify-center" />;
}

window.Icon = Icon;
