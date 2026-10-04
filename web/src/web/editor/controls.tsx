/**
 * Small sidebar controls of the 3D editor (ported from ImageExpress ThreeDLayerEditor.tsx).
 */
import React from "react";

export const SectionTitle = ({ icon, children, right }: { icon: React.ReactNode; children: React.ReactNode; right?: React.ReactNode }) => (
    <h4 className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mt-4 mb-2 first:mt-0">
        {icon}
        <span className="flex-1">{children}</span>
        {right}
    </h4>
);

export const MiniSlider = ({
    label,
    value,
    min,
    max,
    step,
    onChange,
    format,
    testId,
}: {
    label: string;
    value: number;
    min: number;
    max: number;
    step: number;
    onChange: (v: number) => void;
    format?: (v: number) => string;
    testId?: string;
}) => (
    <div className="space-y-1">
        <div className="flex justify-between text-[10px] text-muted-foreground uppercase">
            <span>{label}</span>
            <span>{format ? format(value) : value}</span>
        </div>
        <input
            data-testid={testId}
            type="range"
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(e) => onChange(parseFloat(e.target.value))}
            onDoubleClick={() => onChange(min <= 0 && max >= 0 ? 0 : min)}
            className="w-full h-1 bg-secondary rounded-lg appearance-none cursor-pointer"
        />
    </div>
);

export const MiniToggle = ({ label, checked, onChange, testId }: { label: string; checked: boolean; onChange: (v: boolean) => void; testId?: string }) => (
    <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground uppercase">{label}</span>
        <button
            type="button"
            data-testid={testId}
            role="switch"
            aria-checked={checked}
            aria-label={label}
            className={`w-8 h-4 rounded-full p-0.5 cursor-pointer transition-colors ${checked ? "bg-primary" : "bg-secondary"}`}
            onClick={() => onChange(!checked)}
        >
            <div className={`w-3 h-3 bg-white rounded-full shadow-sm transition-transform ${checked ? "translate-x-4" : "translate-x-0"}`} />
        </button>
    </div>
);

/** Approximate sRGB colour of a black body at `kelvin` (Tanner Helland's fit). */
export function kelvinToHex(kelvin: number): string {
    const t = Math.min(40000, Math.max(1000, kelvin)) / 100;
    const r = t <= 66 ? 255 : 329.698727446 * Math.pow(t - 60, -0.1332047592);
    const g = t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * Math.pow(t - 60, -0.0755148492);
    const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307;
    const c = (v: number) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, "0");
    return `#${c(r)}${c(g)}${c(b)}`;
}

const SWATCHES = ["#ffffff", "#fff6ec", "#fff7e0", "#ffd9a8", "#ffb36b", "#ff8a4c", "#cfe4ff", "#8fa8ff", "#b9ffd6", "#ff9ad5"];

/**
 * Light colour picker that works inside Photoshop's WebView (whose native colour popup,
 * like <select>'s, does not paint): swatches, a colour-temperature slider and a hex field.
 */
export function ColorField({ value, onChange }: { value: string; onChange: (hex: string) => void }) {
    const [text, setText] = React.useState(value);
    const [kelvin, setKelvin] = React.useState(6500);
    React.useEffect(() => setText(value), [value]);
    const commit = () => {
        const m = /^#?([0-9a-f]{6})$/i.exec(text.trim());
        if (m) onChange(`#${m[1].toLowerCase()}`);
        else setText(value);
    };
    return (
        <div className="space-y-1.5">
            <div className="flex justify-between text-[10px] text-muted-foreground uppercase">
                <span>Color</span>
                <span className="w-3 h-3 rounded-sm border border-border" style={{ backgroundColor: value }} />
            </div>
            <div className="grid grid-cols-10 gap-0.5">
                {SWATCHES.map((c) => (
                    <button key={c} type="button" title={c} aria-label={`Light color ${c}`} onClick={() => onChange(c)} className={`h-4 rounded-sm border ${value === c ? "border-primary ring-1 ring-primary" : "border-border"}`} style={{ backgroundColor: c }} />
                ))}
            </div>
            <MiniSlider
                label="Temperature"
                value={kelvin}
                min={1900}
                max={12000}
                step={100}
                format={(v) => `${v} K`}
                onChange={(k) => {
                    setKelvin(k);
                    onChange(kelvinToHex(k));
                }}
            />
            <input value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} aria-label="Light color hex" className="w-full h-6 bg-input border border-border rounded px-2 text-[11px] font-mono" />
        </div>
    );
}

export const ChipButton =({ active, onClick, children, title }: { active?: boolean; onClick: () => void; children: React.ReactNode; title?: string }) => (
    <button
        type="button"
        title={title}
        onClick={onClick}
        className={`flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md border text-[10px] transition-colors text-left ${
            active ? "bg-primary text-primary-foreground border-primary" : "bg-muted hover:bg-secondary border-transparent"
        }`}
    >
        {children}
    </button>
);
