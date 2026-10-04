/**
 * In-page dropdown used instead of <select>.
 *
 * Inside Photoshop's UXP WebView a native <select> opens its popup as a separate
 * window that is never painted (an empty black box), so every choice in the UI uses
 * this component: a button plus a list rendered in the page, opening up or down
 * depending on the space left. Keyboard: arrows, Home/End, Enter, Escape, type-ahead.
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";

export type DropdownOption<T extends string> = { value: T; label: string; hint?: string };

export function Dropdown<T extends string>({
    value,
    options,
    onChange,
    className = "w-full",
    ariaLabel,
    testId,
}: {
    value: T;
    options: readonly DropdownOption<T>[];
    onChange: (v: T) => void;
    className?: string;
    ariaLabel?: string;
    testId?: string;
}) {
    const [open, setOpen] = useState(false);
    const [active, setActive] = useState(0);
    const [up, setUp] = useState(false);
    const root = useRef<HTMLDivElement>(null);
    const list = useRef<HTMLUListElement>(null);
    const selected = options.find((o) => o.value === value);

    useEffect(() => {
        if (!open) return;
        const close = (e: MouseEvent) => {
            if (!root.current?.contains(e.target as Node)) setOpen(false);
        };
        window.addEventListener("mousedown", close);
        return () => window.removeEventListener("mousedown", close);
    }, [open]);

    useLayoutEffect(() => {
        if (!open || !root.current) return;
        const r = root.current.getBoundingClientRect();
        const below = window.innerHeight - r.bottom;
        setUp(below < Math.min(220, options.length * 26 + 8) && r.top > below);
        setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    }, [open, options, value]);

    useEffect(() => {
        if (open) list.current?.children[active]?.scrollIntoView({ block: "nearest" });
    }, [active, open]);

    const choose = (i: number) => {
        const o = options[i];
        if (o) onChange(o.value);
        setOpen(false);
    };

    const onKey = (e: React.KeyboardEvent) => {
        if (!open && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            setOpen(true);
            return;
        }
        if (!open) return;
        if (e.key === "Escape") setOpen(false);
        else if (e.key === "ArrowDown") setActive((a) => Math.min(options.length - 1, a + 1));
        else if (e.key === "ArrowUp") setActive((a) => Math.max(0, a - 1));
        else if (e.key === "Home") setActive(0);
        else if (e.key === "End") setActive(options.length - 1);
        else if (e.key === "Enter" || e.key === " ") choose(active);
        else if (e.key.length === 1) {
            const i = options.findIndex((o) => o.label.toLowerCase().startsWith(e.key.toLowerCase()));
            if (i >= 0) setActive(i);
            return;
        } else return;
        e.preventDefault();
    };

    return (
        <div ref={root} className={`relative ${className}`}>
            <button
                type="button"
                aria-haspopup="listbox"
                aria-expanded={open}
                aria-label={ariaLabel}
                data-testid={testId}
                onClick={() => setOpen(!open)}
                onKeyDown={onKey}
                className="w-full h-7 bg-input border border-border rounded px-2 text-xs flex items-center gap-1 text-left outline-none focus:border-primary"
            >
                <span className="flex-1 truncate">{selected?.label ?? value}</span>
                <ChevronDown size={12} className="text-muted-foreground shrink-0" />
            </button>
            {open && (
                <ul
                    ref={list}
                    role="listbox"
                    className={`absolute z-50 left-0 right-0 max-h-56 overflow-auto rounded border border-border bg-card shadow-xl py-1 ${up ? "bottom-full mb-1" : "top-full mt-1"}`}
                >
                    {options.map((o, i) => (
                        <li
                            key={o.value}
                            role="option"
                            aria-selected={o.value === value}
                            onMouseEnter={() => setActive(i)}
                            onMouseDown={(e) => {
                                e.preventDefault();
                                choose(i);
                            }}
                            className={`px-2 py-1 text-xs flex items-center gap-1.5 cursor-pointer ${i === active ? "bg-primary text-primary-foreground" : ""}`}
                        >
                            <span className="w-3 shrink-0">{o.value === value && <Check size={11} />}</span>
                            <span className="flex-1 truncate">{o.label}</span>
                            {o.hint && <span className={`text-[10px] ${i === active ? "opacity-80" : "text-muted-foreground"}`}>{o.hint}</span>}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
