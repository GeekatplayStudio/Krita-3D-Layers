/**
 * In-page tooltips for `title` attributes.
 *
 * Inside Photoshop's UXP WebView, native tooltips (like <select> popups) open as separate
 * windows that are never painted — they show as empty black boxes. This takes over every
 * element with a `title`: the attribute is moved to `data-tip` on hover (so the browser
 * shows nothing) and the text is drawn in a small div near the pointer instead.
 */
let tip: HTMLDivElement | null = null;
let timer: number | null = null;

function ensureTip(): HTMLDivElement {
    if (tip) return tip;
    tip = document.createElement("div");
    tip.setAttribute("role", "tooltip");
    tip.style.cssText =
        "position:fixed;z-index:2147483647;pointer-events:none;max-width:260px;padding:4px 7px;border-radius:4px;" +
        "font:11px/1.35 var(--font-sans, sans-serif);white-space:pre-line;background:var(--ps-card,#2b2b2b);color:var(--ps-fg,#e6e6e6);" +
        "border:1px solid var(--ps-border,#4a4a4a);box-shadow:0 4px 14px rgba(0,0,0,.35);opacity:0;transition:opacity .08s";
    document.body.appendChild(tip);
    return tip;
}

function hide() {
    if (timer) window.clearTimeout(timer);
    timer = null;
    if (tip) tip.style.opacity = "0";
}

function show(text: string, x: number, y: number) {
    const el = ensureTip();
    el.textContent = text;
    el.style.opacity = "1";
    const pad = 8;
    const r = el.getBoundingClientRect();
    let left = x + 12;
    let top = y + 16;
    if (left + r.width > window.innerWidth - pad) left = Math.max(pad, window.innerWidth - r.width - pad);
    if (top + r.height > window.innerHeight - pad) top = Math.max(pad, y - r.height - 10);
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
}

export function installTooltips(delayMs = 450): void {
    document.addEventListener(
        "mouseover",
        (e) => {
            const target = (e.target as Element | null)?.closest?.("[title],[data-tip]") as HTMLElement | null;
            if (!target) return;
            const title = target.getAttribute("title");
            if (title) {
                target.setAttribute("data-tip", title);
                target.removeAttribute("title");
            }
            const text = target.getAttribute("data-tip");
            if (!text) return;
            hide();
            const { clientX, clientY } = e as MouseEvent;
            timer = window.setTimeout(() => show(text, clientX, clientY), delayMs);
        },
        true,
    );
    document.addEventListener(
        "mouseout",
        (e) => {
            const from = (e.target as Element | null)?.closest?.("[data-tip]");
            const to = (e.relatedTarget as Element | null)?.closest?.("[data-tip]");
            if (from && from !== to) hide();
        },
        true,
    );
    document.addEventListener("mousedown", hide, true);
    document.addEventListener("wheel", hide, { capture: true, passive: true });
}
