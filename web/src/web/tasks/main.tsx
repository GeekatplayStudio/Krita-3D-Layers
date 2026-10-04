/**
 * tasks.html: work Krita hands to the browser because it needs three.js:
 * - "import": convert FBX, OBJ, USDZ, STL… to GLB (the Photoshop plugin's converter,
 *   src/web/panel/importModels.ts) and add them to the library;
 * - "thumbnails": render a preview for library models that have none.
 * When it is done the page reports back (tasks.done) and closes itself.
 *
 * Krita plugin: this file is Krita-owned (scripts/sync-web.mjs never overwrites it).
 */
import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "../styles.css";
import type { ImportBatch } from "@shared/modelFormats";
import { getBridge } from "../bridge/client";
import { kritaCall } from "../bridge/httpTransport";
import { processImportBatch, type ImportReport } from "../panel/importModels";

type Task = { kind: "import" | "thumbnails"; batch?: ImportBatch; items?: { id: string; name: string; modelFile: string }[] };
type Result = { added: number; failed: { name: string; error: string }[]; notes: string[]; previews: number };

async function renderPreviews(items: { id: string; name: string; modelFile: string }[], onStatus: (m: string) => void): Promise<number> {
    const b = await getBridge();
    const { renderModelThumbnail } = await import("../three/thumbnail");
    let made = 0;
    for (const [i, item] of items.entries()) {
        onStatus(`Rendering a preview of ${item.name} (${i + 1} of ${items.length})`);
        try {
            const png = await renderModelThumbnail(`./library/${item.modelFile}`, 384);
            await b.call("library.saveThumbnail", { id: item.id, pngBase64: png.replace(/^data:[^,]*,/, "") });
            made++;
        } catch (err) {
            void b.call("log.write", { level: "warn", message: `tasks: no preview for ${item.name}: ${(err as Error).message}` });
        }
    }
    return made;
}

function TasksApp() {
    const [status, setStatus] = useState("Starting…");
    const [result, setResult] = useState<Result | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        (async () => {
            const b = await getBridge();
            const info = await b.call("app.info");
            document.documentElement.dataset.theme = info.theme;
            const task = await kritaCall<Task>("tasks.get");
            let report: ImportReport = { added: 0, failed: [], notes: [] };
            if (task.kind === "import" && task.batch) report = await processImportBatch(task.batch, (m) => m && setStatus(m));
            // New imports (and anything else without a preview) get one now.
            const missing = await kritaCall<{ id: string; name: string; modelFile: string }[]>("tasks.missingThumbnails");
            const previews = missing.length ? await renderPreviews(missing, setStatus) : 0;
            const out: Result = { ...report, previews };
            await kritaCall("tasks.done", out);
            setResult(out);
            window.setTimeout(() => window.close(), out.failed.length ? 8000 : 1500);
        })().catch((err: Error) => {
            setError(err.message);
            void kritaCall("tasks.done", { added: 0, failed: [{ name: "", error: err.message }], notes: [], previews: 0 }).catch(() => undefined);
        });
    }, []);

    return (
        <div className="h-full flex flex-col items-center justify-center gap-3 p-6 text-center bg-card text-foreground" data-testid="tasks">
            <p className="text-sm font-medium">Geekatplay 3D Layers</p>
            {!result && !error && <p className="text-xs text-muted-foreground" data-testid="task-status">{status}</p>}
            {result && (
                <div className="text-xs space-y-1" data-testid="task-result">
                    <p>
                        {result.added ? `Added ${result.added} model${result.added === 1 ? "" : "s"} to the library.` : "Nothing new was added."}
                        {result.previews ? ` Made ${result.previews} preview${result.previews === 1 ? "" : "s"}.` : ""}
                    </p>
                    {result.failed.map((f) => (
                        <p key={f.name + f.error} className="text-danger">
                            {f.name}: {f.error}
                        </p>
                    ))}
                    <p className="text-muted-foreground">You can close this window.</p>
                </div>
            )}
            {error && <p className="text-xs text-danger">{error}</p>}
        </div>
    );
}

createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
        <TasksApp />
    </React.StrictMode>,
);
