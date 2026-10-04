/**
 * Page side of the bridge (see src/shared/protocol.ts).
 *
 * Inside Photoshop the page talks to the UXP host through `window.uxpHost`. In Krita it
 * talks to the plugin's local server over HTTP (./httpTransport). In a normal browser
 * (`npm run dev`, Playwright tests) there is no host, so the mock in ./mockHost answers
 * instead — the UI code cannot tell the difference.
 *
 * Krita plugin: this file is Krita-owned (scripts/sync-web.mjs never overwrites it).
 */
import { isBridgeMessage, type HostEventName, type HostEvents, type HostMethod, type ParamsOf, type ResultOf } from "@shared/protocol";
import { httpTransport, inKrita } from "./httpTransport";

export interface Transport {
    send(message: unknown): void;
    onMessage(fn: (message: unknown) => void): void;
}

declare global {
    interface Window {
        uxpHost?: { postMessage(message: unknown): void };
        __ps3dMockHost?: Transport;
    }
}

export class BridgeClient {
    private nextId = 1;
    private pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void; method: string }>();
    private listeners = new Map<string, Set<(data: unknown) => void>>();

    constructor(private readonly transport: Transport) {
        transport.onMessage((raw) => this.receive(raw));
    }

    private receive(raw: unknown) {
        let data = raw;
        if (typeof data === "string") {
            try {
                data = JSON.parse(data);
            } catch {
                return;
            }
        }
        if (!isBridgeMessage(data)) return;
        if (data.t === "res") {
            const p = this.pending.get(data.id);
            if (!p) return;
            this.pending.delete(data.id);
            if (data.ok) p.resolve(data.result);
            else p.reject(new Error(data.error?.message ?? `${p.method} failed`));
        } else if (data.t === "evt") {
            for (const fn of this.listeners.get(data.name) ?? []) fn(data.data);
        }
    }

    call<M extends HostMethod>(method: M, ...args: ParamsOf<M> extends void ? [] : [ParamsOf<M>]): Promise<ResultOf<M>> {
        const id = this.nextId++;
        return new Promise<ResultOf<M>>((resolve, reject) => {
            this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, method });
            this.transport.send({ t: "req", id, method, params: args[0] ?? null });
        });
    }

    on<E extends HostEventName>(name: E, fn: (data: HostEvents[E]) => void): () => void {
        const set = this.listeners.get(name) ?? new Set();
        set.add(fn as (d: unknown) => void);
        this.listeners.set(name, set);
        return () => set.delete(fn as (d: unknown) => void);
    }
}

function uxpTransport(): Transport | null {
    if (typeof window === "undefined" || !window.uxpHost) return null;
    return {
        send: (m) => window.uxpHost!.postMessage(m),
        onMessage: (fn) => window.addEventListener("message", (e) => fn(e.data)),
    };
}

let client: BridgeClient | null = null;

/** The bridge for this page: real host in Photoshop, mock host elsewhere. */
export async function getBridge(): Promise<BridgeClient> {
    if (client) return client;
    const real = uxpTransport() ?? (inKrita() ? httpTransport() : null);
    if (real) client = new BridgeClient(real);
    else {
        const { createMockTransport } = await import("./mockHost");
        client = new BridgeClient(window.__ps3dMockHost ?? createMockTransport());
    }
    return client;
}

/** Synchronous access after getBridge() resolved (set up in main.tsx). */
export function bridge(): BridgeClient {
    if (!client) throw new Error("Bridge not initialised");
    return client;
}

export const inPhotoshop = () => typeof window !== "undefined" && !!window.uxpHost;
