const { useEffect, useRef } = React;

function Icon({ name, className = "" }) {
    const ref = useRef(null);
    useEffect(() => {
        if (ref.current && window.lucide) {
            ref.current.innerHTML = `<i data-lucide="${name}" class="${className}"></i>`;
            window.lucide.createIcons({
                node: ref.current
            });
        }
    }, [name, className]);

    return <span ref={ref} className="inline-flex items-center justify-center" />;
}

window.Icon = Icon;
