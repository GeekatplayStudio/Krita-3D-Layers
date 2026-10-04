/**
 * Reads and writes the 3D state stored in a layer's XMP metadata.
 *
 * Photoshop keeps per-layer XMP (batchPlay property "XMPMetadataAsUTF8"). It is
 * saved inside the PSD, survives "Replace Contents" on smart objects, and is
 * invisible to the user — the right place for "which model, posed how, lit how".
 * The state is one JSON string in the element <ps3d:state> under our namespace,
 * XML-escaped. Other XMP on the layer is preserved.
 */
import type { LayerState } from "./types";

export const XMP_NS = "http://ns.geekatplay.com/photoshop3d/1.0/";
export const XMP_PREFIX = "ps3d";

const STATE_RE = /<ps3d:state>([\s\S]*?)<\/ps3d:state>/;

export function escapeXml(text: string): string {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
}

export function unescapeXml(text: string): string {
    return text
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"')
        .replace(/&apos;/g, "'")
        .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(Number(d)))
        .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
        .replace(/&amp;/g, "&");
}

function description(state: LayerState): string {
    return `<rdf:Description rdf:about="" xmlns:${XMP_PREFIX}="${XMP_NS}"><ps3d:state>${escapeXml(JSON.stringify(state))}</ps3d:state></rdf:Description>`;
}

/** Returns `existing` XMP with our state set (replacing a previous one), or a new packet. */
export function writeLayerStateXmp(existing: string | undefined | null, state: LayerState): string {
    const xml = existing?.trim() ?? "";
    if (STATE_RE.test(xml)) {
        return xml.replace(STATE_RE, `<ps3d:state>${escapeXml(JSON.stringify(state))}</ps3d:state>`);
    }
    if (xml.includes("</rdf:RDF>")) {
        return xml.replace("</rdf:RDF>", `${description(state)}</rdf:RDF>`);
    }
    return (
        `<x:xmpmeta xmlns:x="adobe:ns:meta/">` +
        `<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">${description(state)}</rdf:RDF>` +
        `</x:xmpmeta>`
    );
}

/** Removes our state from layer XMP; returns "" when nothing else was in it. */
export function removeLayerStateXmp(existing: string | undefined | null): string {
    const xml = existing ?? "";
    const withoutOurs = xml.replace(/<rdf:Description[^>]*xmlns:ps3d=[^>]*>\s*<ps3d:state>[\s\S]*?<\/ps3d:state>\s*<\/rdf:Description>/, "");
    const cleaned = withoutOurs.replace(STATE_RE, "");
    return /<rdf:Description/.test(cleaned) ? cleaned : "";
}

/** Parses our state from layer XMP; null when absent or not ours/invalid. */
export function readLayerStateXmp(xmp: string | undefined | null): LayerState | null {
    if (!xmp) return null;
    const match = STATE_RE.exec(xmp);
    if (!match) return null;
    try {
        const parsed = JSON.parse(unescapeXml(match[1])) as LayerState;
        if (!parsed || parsed.v !== 1 || typeof parsed.libraryId !== "string" || !parsed.settings) return null;
        return parsed;
    } catch {
        return null;
    }
}
