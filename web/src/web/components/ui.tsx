/**
 * Small UI kit for the panel, styled to sit quietly inside Photoshop.
 */
import React, { useState } from "react";
import { ChevronDown, ChevronRight, ClipboardPaste, Loader2 } from "lucide-react";
import { bridge } from "../bridge/client";
import { Dropdown } from "./Dropdown";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; busy?: boolean; icon?: React.ReactNode };

export function Button({ variant = "secondary", size = "md", busy, icon, children, className = "", disabled, ...rest }: ButtonProps) {
    const base = "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap";
    const sizes = { sm: "h-6 px-2 text-[11px]", md: "h-8 px-3 text-xs" };
    const variants = {
        primary: "bg-primary text-primary-foreground hover:opacity-90",
        secondary: "bg-secondary text-foreground hover:bg-muted border border-border",
        ghost: "text-muted-foreground hover:text-foreground hover:bg-secondary",
        danger: "bg-danger/90 text-white hover:bg-danger",
    };
    return (
        <button type="button" className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} disabled={disabled || busy} {...rest}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : icon}
            {children}
        </button>
    );
}

/**
 * Pastes the clipboard into a field. Needed in the docked panel: Photoshop keeps Ctrl/Cmd+V
 * for its own Paste, so the shortcut never reaches inputs inside the panel's WebView.
 */
export function PasteButton({ onPaste, title = "Paste from clipboard" }: { onPaste: (text: string) => void; title?: string }) {
    const [busy, setBusy] = useState(false);
    return (
        <Button
            size="md"
            variant="ghost"
            title={title}
            aria-label={title}
            busy={busy}
            icon={<ClipboardPaste size={13} />}
            onClick={async () => {
                setBusy(true);
                try {
                    const text = (await bridge().call("clipboard.readText")).trim();
                    if (text) onPaste(text);
                } catch {
                    // Clipboard unavailable: the user can still type.
                } finally {
                    setBusy(false);
                }
            }}
        />
    );
}

export function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
    return (
        <label className="block space-y-1">
            <span className="block text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
            {children}
            {hint && <span className="block text-[10px] text-muted-foreground leading-snug">{hint}</span>}
        </label>
    );
}

export const inputClass = "w-full h-7 bg-input border border-border rounded px-2 text-xs outline-none focus:border-primary";

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
    return <input {...props} className={`${inputClass} ${props.className ?? ""}`} />;
}

/** A choice list. Never a native <select>: its popup does not paint in Photoshop's WebView (see Dropdown). */
export function Select<T extends string>({
    value,
    options,
    onChange,
    className,
    "data-testid": testId,
    "aria-label": ariaLabel,
}: {
    value: T;
    options: readonly (T | { value: T; label: string; hint?: string })[];
    onChange: (v: T) => void;
    className?: string;
    "data-testid"?: string;
    "aria-label"?: string;
}) {
    const opts = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
    return <Dropdown value={value} options={opts} onChange={onChange} className={className ?? "w-full"} testId={testId} ariaLabel={ariaLabel} />;
}

export function Toggle({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string }) {
    return (
        <label className="flex items-start gap-2 cursor-pointer py-0.5">
            <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 accent-[var(--ps-accent)]" />
            <span className="text-xs leading-snug">
                {label}
                {hint && <span className="block text-[10px] text-muted-foreground">{hint}</span>}
            </span>
        </label>
    );
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "success" | "warning" | "danger" | "info"; children: React.ReactNode }) {
    const tones = {
        neutral: "bg-secondary text-muted-foreground",
        success: "bg-success/20 text-success",
        warning: "bg-warning/20 text-warning",
        danger: "bg-danger/20 text-danger",
        info: "bg-primary/20 text-primary",
    };
    return <span className={`inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium ${tones[tone]}`}>{children}</span>;
}

export function ProgressBar({ value, indeterminate }: { value: number; indeterminate?: boolean }) {
    return (
        <div className="h-1 w-full rounded bg-secondary overflow-hidden">
            <div className={`h-full bg-primary transition-all ${indeterminate ? "animate-pulse w-full opacity-60" : ""}`} style={indeterminate ? undefined : { width: `${Math.max(2, Math.min(100, value))}%` }} />
        </div>
    );
}

export function Section({ title, children, defaultOpen = true, right, testId }: { title: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean; right?: React.ReactNode; testId?: string }) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <section className="border border-border rounded-md bg-card" data-testid={testId}>
            <header className="flex items-center gap-1 px-2 h-8 cursor-pointer" onClick={() => setOpen(!open)}>
                {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                <span className="flex-1 text-xs font-semibold">{title}</span>
                <span onClick={(e) => e.stopPropagation()}>{right}</span>
            </header>
            {open && <div className="px-3 pb-3 pt-1 space-y-2.5">{children}</div>}
        </section>
    );
}

export function Empty({ icon, title, children }: { icon?: React.ReactNode; title: string; children?: React.ReactNode }) {
    return (
        <div className="flex flex-col items-center justify-center text-center gap-2 py-8 px-4 text-muted-foreground">
            {icon}
            <div className="text-xs font-medium text-foreground">{title}</div>
            {children && <div className="text-[11px] leading-snug max-w-[240px]">{children}</div>}
        </div>
    );
}

export function timeAgo(ms?: number): string {
    if (!ms) return "";
    const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return new Date(ms).toLocaleDateString();
}
