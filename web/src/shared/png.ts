/**
 * PNG encoding in plain JS (UXP has no canvas encoder that keeps alpha:
 * imaging.encodeImageData only produces JPEG). Used by the host to turn the
 * layer pixels from imaging.getPixels into a PNG for the 3D services.
 */
import { zlibSync } from "fflate";

const CRC_TABLE = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
        let c = n;
        for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
        t[n] = c >>> 0;
    }
    return t;
})();

function crc32(data: Uint8Array, start = 0, end = data.length): number {
    let c = 0xffffffff;
    for (let i = start; i < end; i++) c = CRC_TABLE[(c ^ data[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
}

function chunk(type: string, data: Uint8Array): Uint8Array {
    const out = new Uint8Array(12 + data.length);
    const view = new DataView(out.buffer);
    view.setUint32(0, data.length);
    for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
    out.set(data, 8);
    view.setUint32(8 + data.length, crc32(out, 4, 8 + data.length));
    return out;
}

/**
 * Encodes 8-bit chunky pixels (RGB when components = 3, RGBA when 4,
 * gray/gray+alpha for 1/2) into a PNG. Rows use the "Up" filter, which
 * compresses photographic layer content well at negligible cost.
 */
export function encodePng(pixels: Uint8Array, width: number, height: number, components: 1 | 2 | 3 | 4, level: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 = 6): Uint8Array {
    if (pixels.length < width * height * components) throw new Error(`encodePng: expected ${width * height * components} bytes, got ${pixels.length}`);
    const colorType = { 1: 0, 2: 4, 3: 2, 4: 6 }[components];
    const ihdr = new Uint8Array(13);
    const v = new DataView(ihdr.buffer);
    v.setUint32(0, width);
    v.setUint32(4, height);
    ihdr[8] = 8;
    ihdr[9] = colorType;
    ihdr[10] = 0;
    ihdr[11] = 0;
    ihdr[12] = 0;

    const stride = width * components;
    const raw = new Uint8Array((stride + 1) * height);
    for (let y = 0; y < height; y++) {
        const rowStart = y * (stride + 1);
        const src = y * stride;
        if (y === 0) {
            raw[rowStart] = 0; // None
            raw.set(pixels.subarray(src, src + stride), rowStart + 1);
        } else {
            raw[rowStart] = 2; // Up
            const prev = src - stride;
            for (let x = 0; x < stride; x++) raw[rowStart + 1 + x] = (pixels[src + x] - pixels[prev + x]) & 0xff;
        }
    }
    const idat = zlibSync(raw, { level });
    const signature = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
    const parts = [signature, chunk("IHDR", ihdr), chunk("IDAT", idat), chunk("IEND", new Uint8Array(0))];
    const total = parts.reduce((n, p) => n + p.length, 0);
    const out = new Uint8Array(total);
    let o = 0;
    for (const p of parts) {
        out.set(p, o);
        o += p.length;
    }
    return out;
}

/** Width/height from a PNG header, or null when the bytes are not a PNG. */
export function pngSize(bytes: Uint8Array): { width: number; height: number } | null {
    if (bytes.length < 24 || bytes[0] !== 0x89 || bytes[1] !== 0x50) return null;
    const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    return { width: v.getUint32(16), height: v.getUint32(20) };
}

/**
 * Applies a selection mask to chunky pixels: returns RGBA where alpha is the
 * source alpha (or 255) multiplied by the mask. `mask` is 8-bit, one byte per pixel.
 */
export function applyMask(pixels: Uint8Array, components: number, mask: Uint8Array, width: number, height: number): Uint8Array {
    const out = new Uint8Array(width * height * 4);
    for (let i = 0, p = 0, o = 0; i < width * height; i++, p += components, o += 4) {
        if (components >= 3) {
            out[o] = pixels[p];
            out[o + 1] = pixels[p + 1];
            out[o + 2] = pixels[p + 2];
        } else {
            out[o] = out[o + 1] = out[o + 2] = pixels[p];
        }
        const a = components === 4 ? pixels[p + 3] : components === 2 ? pixels[p + 1] : 255;
        out[o + 3] = Math.round((a * mask[i]) / 255);
    }
    return out;
}
