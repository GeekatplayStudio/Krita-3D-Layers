/**
 * Entry of editor.html for Krita: the 3D editor in a browser window opened by the plugin.
 *
 * Same editor as in Photoshop (ThreeDLayerEditor); what differs is the window around it:
 * - the page asks Krita what to edit (editor.getInit) and sends the render back
 *   (editor.complete) or cancels (editor.cancel), then closes its own window;
 * - closing the window early cancels the session (a beacon on pagehide, plus a heartbeat
 *   so Krita notices a crashed or killed browser);
 * - a model without a library preview gets one rendered here (Krita cannot draw 3D).
 *
 * Krita plugin: this file is Krita-owned (scripts/sync-web.mjs never overwrites it).
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";
import type { EditorInit, EditorResult } from "@shared/protocol";
import type { LightingDefaults } from "@shared/threeD";
import type { EditorViewPrefs } from "@shared/settings";
import { bridge, getBridge } from "../bridge/client";
import { beacon, inKrita, kritaCall } from "../bridge/httpTransport";
import { modelUrl, resolveLibraryBase } from "../three/modelSource";
import ThreeDLayerEditor from "./ThreeDLayerEditor";
import { installTooltips } from "../components/tooltips";

installTooltips();

type KritaInit = EditorInit & { makeThumbnail?: boolean };

function Finished({ message }: { message: string }) {
    useEffect(() => {
        // An app window opened by the plugin may close itself; a normal tab may refuse.
        const t = window.setTimeout(() => window.close(), 400);
        return () => window.clearTimeout(t);
    }, []);
    return (
        <div className="h-full flex flex-col items-center justify-center gap-2 p-6 text-center" data-testid="finished">
            <p className="text-sm">{message}</p>
            <p className="text-xs text-muted-foreground">You can close this window and go back to Krita.</p>
        </div>
    );
}

function EditorApp() {
    const [init, setInit] = useState<KritaInit | null>(null);
    const [url, setUrl] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [finished, setFinished] = useState<string | null>(null);
    const done = useRef(false);

    useEffect(() => {
        (async () => {
            const b = await getBridge();
            const info = await b.call("app.info");
            document.documentElement.dataset.theme = info.theme;
            const data = (await b.call("editor.getInit")) as KritaInit;
            document.title = `${data.mode === "update" ? "Edit 3D Layer" : "Place 3D Model"} — ${data.model.name}`;
            setInit(data);
            const base = await resolveLibraryBase(info.libraryBaseUrl);
            const model = base && data.model.url ? data.model.url : await modelUrl(null, data.model.file);
            setUrl(model);
            if (data.makeThumbnail) {
                // Low priority: after the editor has drawn its first frames.
                window.setTimeout(async () => {
                    try {
                        const { renderModelThumbnail } = await import("../three/thumbnail");
                        const png = await renderModelThumbnail(model, 384);
                        await b.call("library.saveThumbnail", { id: data.model.libraryId, pngBase64: png.replace(/^data:[^,]*,/, "") });
                    } catch (err) {
                        void b.call("log.write", { level: "warn", message: `editor: preview not made: ${(err as Error).message}` });
                    }
                }, 2500);
            }
        })().catch((err: Error) => setError(err.message));
    }, []);

    // Tell Krita we are still here; if the window disappears without OK/Cancel, Krita gives up.
    useEffect(() => {
        if (!inKrita()) return;
        const ping = window.setInterval(() => void kritaCall("editor.ping").catch(() => undefined), 5000);
        const leave = () => {
            if (!done.current) beacon("editor.cancel");
        };
        window.addEventListener("pagehide", leave);
        return () => {
            window.clearInterval(ping);
            window.removeEventListener("pagehide", leave);
        };
    }, []);

    const complete = useCallback(async (result: EditorResult) => {
        await bridge().call("editor.complete", result);
        done.current = true;
        setFinished("Done: the layer is in your Krita document.");
    }, []);
    const cancel = useCallback(() => {
        done.current = true;
        void bridge()
            .call("editor.cancel")
            .finally(() => setFinished("Cancelled. Nothing was changed in Krita."));
    }, []);
    const remember = useCallback((lighting: LightingDefaults) => {
        void bridge().call("editor.rememberLighting", lighting);
    }, []);
    const loadDocumentView = useCallback(() => bridge().call("editor.documentView"), []);
    const rememberView = useCallback((view: EditorViewPrefs) => {
        void bridge().call("editor.rememberView", view);
    }, []);

    if (finished) return <Finished message={finished} />;
    if (error) {
        return (
            <div className="h-full flex flex-col items-center justify-center gap-3 p-6 text-center">
                <p className="text-sm">The 3D editor could not start.</p>
                <p className="text-xs text-muted-foreground max-w-md">{error}</p>
                <button type="button" className="px-3 py-1.5 rounded border border-border text-xs" onClick={cancel}>
                    Close
                </button>
            </div>
        );
    }
    if (!init || !url) return <div className="h-full flex items-center justify-center text-xs text-muted-foreground">Opening the 3D editor…</div>;
    return <ThreeDLayerEditor init={init} modelUrl={url} onComplete={complete} onCancel={cancel} onRememberLighting={remember} loadDocumentView={loadDocumentView} onRememberView={rememberView} />;
}

window.addEventListener("error", (e) => {
    void getBridge().then((b) => b.call("log.write", { level: "error", message: `editor: ${e.message}`, data: { file: e.filename, line: e.lineno } }));
});

createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
        <EditorApp />
    </React.StrictMode>,
);
