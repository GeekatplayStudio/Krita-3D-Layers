/**
 * Byte helpers that work in UXP (no Buffer, no TextEncoder), browsers and Node.
 */
import { decodeUtf8, encodeUtf8 } from "./utf8";

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
const LOOKUP = (() => {
    const t = new Uint8Array(256).fill(255);
    for (let i = 0; i < ALPHABET.length; i++) t[ALPHABET.charCodeAt(i)] = i;
    t["-".charCodeAt(0)] = 62; // base64url
    t["_".charCodeAt(0)] = 63;
    return t;
})();

/** Base64 without btoa's binary-string round trip (fast for tens of MB). */
export function bytesToBase64(bytes: Uint8Array): string {
    const parts: string[] = [];
    const CHUNK = 0x8000 * 3; // multiple of 3 so chunks concatenate cleanly
    for (let start = 0; start < bytes.length; start += CHUNK) {
        const end = Math.min(bytes.length, start + CHUNK);
        let out = "";
        let i = start;
        for (; i + 2 < end; i += 3) {
            const n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
            out += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63] + ALPHABET[n & 63];
        }
        const rest = end - i;
        if (rest === 1) {
            const n = bytes[i] << 16;
            out += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63] + "==";
        } else if (rest === 2) {
            const n = (bytes[i] << 16) | (bytes[i + 1] << 8);
            out += ALPHABET[(n >> 18) & 63] + ALPHABET[(n >> 12) & 63] + ALPHABET[(n >> 6) & 63] + "=";
        }
        parts.push(out);
    }
    return parts.join("");
}

export function base64ToBytes(input: string): Uint8Array {
    const b64 = input.replace(/^data:[^,]*,/, "").replace(/[\s=]/g, "");
    const out = new Uint8Array(Math.floor((b64.length * 3) / 4));
    let o = 0;
    let buffer = 0;
    let bits = 0;
    for (let i = 0; i < b64.length; i++) {
        const v = LOOKUP[b64.charCodeAt(i)];
        if (v === 255) throw new Error(`Invalid base64 character at ${i}`);
        buffer = (buffer << 6) | v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out[o++] = (buffer >> bits) & 0xff;
        }
    }
    return out.subarray(0, o);
}

export function utf8Encode(text: string): Uint8Array {
    return encodeUtf8(text);
}

export function utf8Decode(bytes: Uint8Array): string {
    return decodeUtf8(bytes);
}

/** First bytes of a file → its type, or null. Used to trust content, not URLs. */
export function sniffFormat(bytes: Uint8Array): "glb" | "gltf" | "png" | "jpg" | "webp" | "zip" | null {
    const at = (i: number) => bytes[i];
    if (bytes.length >= 4 && at(0) === 0x67 && at(1) === 0x6c && at(2) === 0x54 && at(3) === 0x46) return "glb"; // "glTF"
    if (bytes.length >= 8 && at(0) === 0x89 && at(1) === 0x50 && at(2) === 0x4e && at(3) === 0x47) return "png";
    if (bytes.length >= 3 && at(0) === 0xff && at(1) === 0xd8 && at(2) === 0xff) return "jpg";
    if (bytes.length >= 12 && at(0) === 0x52 && at(1) === 0x49 && at(2) === 0x46 && at(3) === 0x46 && at(8) === 0x57 && at(9) === 0x45) return "webp";
    if (bytes.length >= 4 && at(0) === 0x50 && at(1) === 0x4b && at(2) === 0x03 && at(3) === 0x04) return "zip";
    if (bytes.length >= 1) {
        // glTF JSON starts with "{" possibly after whitespace/BOM.
        for (let i = 0; i < Math.min(bytes.length, 16); i++) {
            const c = at(i);
            if (c === 0x7b) return "gltf";
            if (c !== 0x20 && c !== 0x0a && c !== 0x0d && c !== 0x09 && c !== 0xef && c !== 0xbb && c !== 0xbf) break;
        }
    }
    return null;
}

export function formatBytes(n: number): string {
    if (!Number.isFinite(n) || n < 0) return "—";
    if (n < 1024) return `${n} B`;
    const units = ["KB", "MB", "GB"];
    let v = n / 1024;
    let u = 0;
    while (v >= 1024 && u < units.length - 1) {
        v /= 1024;
        u++;
    }
    return `${v.toFixed(v < 10 ? 1 : 0)} ${units[u]}`;
}

/** Short random id with a readable prefix: "lib_lx3k9a2f8q". */
export function newId(prefix: string): string {
    const time = Date.now().toString(36);
    const rand = Math.floor(Math.random() * 36 ** 6)
        .toString(36)
        .padStart(6, "0");
    return `${prefix}_${time}${rand}`;
}

/** Safe file-name stem from arbitrary text. */
export function slug(text: string, fallback = "model"): string {
    const s = text
        .normalize("NFKD")
        .replace(/[̀-ͯ]/g, "")
        .replace(/[^a-zA-Z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .toLowerCase()
        .slice(0, 48);
    return s || fallback;
}
