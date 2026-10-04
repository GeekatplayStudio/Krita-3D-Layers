/**
 * UTF-8 encode/decode in plain JS.
 *
 * Photoshop's UXP host JavaScript has no TextEncoder/TextDecoder (verified in UXP 9.4:
 * "TextEncoder is not defined"), so host code uses these, and src/host/polyfills.ts
 * installs them as globals for libraries that expect the standard classes.
 */
export function encodeUtf8(text: string): Uint8Array {
    const out: number[] = [];
    for (let i = 0; i < text.length; i++) {
        let cp = text.charCodeAt(i);
        if (cp >= 0xd800 && cp <= 0xdbff && i + 1 < text.length) {
            const next = text.charCodeAt(i + 1);
            if (next >= 0xdc00 && next <= 0xdfff) {
                cp = 0x10000 + ((cp - 0xd800) << 10) + (next - 0xdc00);
                i++;
            }
        } else if (cp >= 0xd800 && cp <= 0xdfff) {
            cp = 0xfffd; // lone surrogate
        }
        if (cp < 0x80) out.push(cp);
        else if (cp < 0x800) out.push(0xc0 | (cp >> 6), 0x80 | (cp & 63));
        else if (cp < 0x10000) out.push(0xe0 | (cp >> 12), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
        else out.push(0xf0 | (cp >> 18), 0x80 | ((cp >> 12) & 63), 0x80 | ((cp >> 6) & 63), 0x80 | (cp & 63));
    }
    return Uint8Array.from(out);
}

export function decodeUtf8(bytes: Uint8Array): string {
    let start = 0;
    if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) start = 3; // BOM
    const parts: string[] = [];
    let chunk: number[] = [];
    const flush = () => {
        parts.push(String.fromCharCode(...chunk));
        chunk = [];
    };
    for (let i = start; i < bytes.length; ) {
        const b = bytes[i];
        let cp: number;
        let n: number;
        if (b < 0x80) {
            cp = b;
            n = 1;
        } else if (b >= 0xc2 && b < 0xe0 && i + 1 < bytes.length) {
            cp = ((b & 31) << 6) | (bytes[i + 1] & 63);
            n = 2;
        } else if (b >= 0xe0 && b < 0xf0 && i + 2 < bytes.length) {
            cp = ((b & 15) << 12) | ((bytes[i + 1] & 63) << 6) | (bytes[i + 2] & 63);
            n = 3;
        } else if (b >= 0xf0 && b < 0xf5 && i + 3 < bytes.length) {
            cp = ((b & 7) << 18) | ((bytes[i + 1] & 63) << 12) | ((bytes[i + 2] & 63) << 6) | (bytes[i + 3] & 63);
            n = 4;
        } else {
            cp = 0xfffd;
            n = 1;
        }
        i += n;
        if (cp >= 0x10000) {
            cp -= 0x10000;
            chunk.push(0xd800 + (cp >> 10), 0xdc00 + (cp & 1023));
        } else chunk.push(cp);
        if (chunk.length >= 8192) flush();
    }
    flush();
    return parts.join("");
}
