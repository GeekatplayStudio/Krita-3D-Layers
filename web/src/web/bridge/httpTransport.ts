/**
 * Bridge transport for Krita: requests go to the plugin's local server as HTTP POSTs.
 *
 * Krita has no web view a plugin can use, so the editor runs in a browser window served by
 * the plugin (plugin/geekatplay_3d_layers/ui/server.py) at
 * http://127.0.0.1:<port>/s/<session token>/. Every URL is relative to that folder, so
 * the token travels with each request without being written anywhere else.
 */
import type { Transport } from "./client";

/** True when this page was opened by the Krita plugin. */
export const inKrita = (): boolean => typeof location !== "undefined" && location.protocol === "http:" && /\/s\/[A-Za-z0-9_-]{16,}\//.test(location.pathname);

export function httpTransport(): Transport {
    const listeners: ((m: unknown) => void)[] = [];
    const deliver = (m: unknown) => listeners.forEach((fn) => fn(m));
    return {
        send(message) {
            const req = message as { t: string; id: number; method: string; params: unknown };
            fetch("./rpc", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ method: req.method, params: req.params }) })
                .then(async (res) => {
                    const body = (await res.json().catch(() => null)) as { ok?: boolean; result?: unknown; error?: string } | null;
                    if (res.ok && body?.ok) deliver({ t: "res", id: req.id, ok: true, result: body.result ?? null });
                    else deliver({ t: "res", id: req.id, ok: false, error: { message: body?.error ?? `Krita answered ${res.status}` } });
                })
                .catch(() => deliver({ t: "res", id: req.id, ok: false, error: { message: "Krita is not reachable. Is it still running with the 3D Layers plugin?" } }));
        },
        onMessage(fn) {
            listeners.push(fn);
        },
    };
}

/** A Krita-only call that is not part of the shared HostApi (heartbeat, task pages). */
export async function kritaCall<T = unknown>(method: string, params: unknown = null): Promise<T> {
    const res = await fetch("./rpc", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ method, params }) });
    const body = (await res.json().catch(() => null)) as { ok?: boolean; result?: T; error?: string } | null;
    if (!res.ok || !body?.ok) throw new Error(body?.error ?? `Krita answered ${res.status}`);
    return body.result as T;
}

/** Fire-and-forget call that survives the page closing (sendBeacon). */
export function beacon(method: string, params: unknown = null): void {
    try {
        navigator.sendBeacon("./rpc", new Blob([JSON.stringify({ method, params })], { type: "text/plain" }));
    } catch {
        // the page is going away anyway
    }
}
