/**
 * Where the WebView loads a library model from.
 *
 * Normally the UI runs from <data>/web and the model is a sibling file, so a relative
 * URL ("../library/<id>/model.glb") is loaded directly. If the host could not copy the
 * UI next to the library, the model bytes come through the bridge and are turned into
 * a blob: URL instead.
 */
import { base64ToBytes } from "@shared/bytes";
import { bridge } from "../bridge/client";

const blobUrls = new Map<string, Promise<string>>();

const reachability = new Map<string, Promise<boolean>>();

/**
 * Checks once whether this WebView may read the library folder directly (the host writes
 * library/.reachable). Returns the base URL to use, or null to stream files through the bridge.
 */
export function resolveLibraryBase(base: string | null): Promise<string | null> {
    if (!base) return Promise.resolve(null);
    let p = reachability.get(base);
    if (!p) {
        p = fetch(`${base}.reachable`, { cache: "no-store" })
            .then(async (r) => r.ok && (await r.text()).trim() === "ok")
            .catch(() => false);
        reachability.set(base, p);
    }
    return p.then((ok) => (ok ? base : null));
}

export function libraryUrl(base: string | null, file: string): string | null {
    if (!base) return null;
    if (/^(data:|blob:|https?:)/.test(file)) return file;
    return `${base}${file}`;
}

export function modelUrl(base: string | null, file: string, mime = "model/gltf-binary"): Promise<string> {
    const direct = libraryUrl(base, file);
    if (direct) return Promise.resolve(direct);
    let p = blobUrls.get(file);
    if (!p) {
        p = bridge()
            .call("library.readFile", { file })
            .then(({ base64 }) => URL.createObjectURL(new Blob([base64ToBytes(base64) as BlobPart], { type: mime })));
        blobUrls.set(file, p);
    }
    return p;
}

/** Same as modelUrl for images (thumbnails). */
export function imageUrl(base: string | null, file: string): Promise<string> {
    if (/^(data:|blob:|https?:)/.test(file)) return Promise.resolve(file);
    return modelUrl(base, file, file.endsWith(".jpg") ? "image/jpeg" : file.endsWith(".webp") ? "image/webp" : "image/png");
}
