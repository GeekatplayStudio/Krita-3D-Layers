/**
 * Runs an import batch from the host: models stored as they were are already in the library;
 * the others are converted here (src/web/three/convert.ts) one at a time and handed back.
 * Imports never overlap: a manual import waits for an Import-folder scan and vice versa.
 */
import { base64ToBytes, bytesToBase64 } from "@shared/bytes";
import { SUPPORTED_FORMATS_TEXT, baseName, extOf, isModelFile, isResourceFile, stripExt, type ImportBatch, type ImportSource } from "@shared/modelFormats";
import { joinFolder, parentFolder } from "@shared/libraryFolders";
import { bridge } from "../bridge/client";

export type ImportReport = { added: number; failed: { name: string; error: string }[]; notes: string[] };

let queue: Promise<unknown> = Promise.resolve();

/** Serialises imports (manual and Import-folder). */
export function enqueueImport<T>(fn: () => Promise<T>): Promise<T> {
    const run = queue.then(fn, fn);
    queue = run.catch(() => undefined);
    return run;
}

/** Reads an import's file: directly when the WebView may, otherwise through the host. */
async function readImportBytes(id: string, url: string, path: string): Promise<Uint8Array> {
    try {
        const res = await fetch(url);
        if (res.ok) return new Uint8Array(await res.arrayBuffer());
    } catch {
        // file:// not readable here; ask the host
    }
    const { base64 } = await bridge().call("library.readImportFile", { id, path });
    return base64ToBytes(base64);
}

async function convertOne(source: ImportSource, onStatus: (message: string) => void): Promise<string[]> {
    // The loaders are large; they load the first time something is converted.
    const { convertToGlb } = await import("../three/convert");
    const result = await convertToGlb(source, (url, path) => readImportBytes(source.id, url, path), onStatus);
    onStatus(`Adding ${source.name} to the library`);
    await bridge().call("library.addConverted", { id: source.id, name: source.name, glbBase64: bytesToBase64(result.glb), sourceFormat: source.ext, notes: result.notes });
    return result.notes;
}

export async function processImportBatch(batch: ImportBatch, onStatus: (message: string | null) => void): Promise<ImportReport> {
    const report: ImportReport = { added: batch.imported.length, failed: [...batch.failed], notes: [] };
    const total = batch.toConvert.length;
    for (const [i, source] of batch.toConvert.entries()) {
        const label = `${source.name}.${source.ext}`;
        try {
            const notes = await convertOne(source, (m) => onStatus(total > 1 ? `${m} (${i + 1} of ${total})` : m));
            report.added++;
            if (notes.length) report.notes.push(`${label}: ${notes.join("; ")}`);
        } catch (err) {
            const error = (err as Error).message || String(err);
            report.failed.push({ name: label, error });
            void bridge()
                .call("library.importFailed", { id: source.id, error })
                .catch(() => undefined);
        }
    }
    onStatus(null);
    return report;
}

/* ------------------------------------------------------------ drag and drop */

/** A file dropped on the panel, with its path inside what was dropped ("Kit/chair/chair.fbx"). */
export type DroppedFile = { file: File; path: string };

const MAX_DROPPED_FILES = 2000;

type FsEntry = { isFile: boolean; isDirectory: boolean; name: string; fullPath: string };
type FileEntry = FsEntry & { file(ok: (f: File) => void, fail: (e: unknown) => void): void };
type DirEntry = FsEntry & { createReader(): { readEntries(ok: (e: FsEntry[]) => void, fail: (e: unknown) => void): void } };

/** Every file dropped, including the contents of dropped folders (and their subfolders). */
export async function collectDropped(dt: DataTransfer): Promise<DroppedFile[]> {
    const out: DroppedFile[] = [];
    const entries = [...dt.items]
        .filter((i) => i.kind === "file")
        .map((i) => (i as DataTransferItem & { webkitGetAsEntry?: () => FsEntry | null }).webkitGetAsEntry?.() ?? null);
    if (!entries.length || entries.some((e) => !e)) {
        // No entry API: plain files only.
        for (const file of [...dt.files]) out.push({ file, path: file.name });
        return out;
    }
    const walk = async (entry: FsEntry, depth: number): Promise<void> => {
        if (out.length >= MAX_DROPPED_FILES) return;
        if (entry.isFile) {
            const file = await new Promise<File>((ok, fail) => (entry as FileEntry).file(ok, fail));
            out.push({ file, path: entry.fullPath.replace(/^\/+/, "") });
        } else if (entry.isDirectory && depth < 8) {
            const reader = (entry as DirEntry).createReader();
            // readEntries returns the folder in batches until an empty one.
            for (;;) {
                const batch = await new Promise<FsEntry[]>((ok, fail) => reader.readEntries(ok, fail));
                if (!batch.length) break;
                for (const child of batch) await walk(child, depth + 1);
            }
        }
    };
    for (const entry of entries) await walk(entry!, 0);
    return out;
}

/**
 * Files dropped from File Explorer / Finder reach a WebView from UXP 9.1 (Photoshop 2026) on;
 * older versions keep the drop. The mock host reports "-" and counts as supported.
 */
export function supportsFileDrop(uxpVersion: string | undefined): boolean {
    const m = /(\d+)\.(\d+)/.exec(uxpVersion ?? "");
    if (!m) return true;
    const [major, minor] = [Number(m[1]), Number(m[2])];
    return major > 9 || (major === 9 && minor >= 1);
}

/** True while something with files is dragged over the panel (not a library card). */
export const isFileDrag = (dt: DataTransfer | null) => !!dt && [...dt.types].includes("Files");

/**
 * Imports dropped files into `into`. Dropped folders become library folders (with their
 * subfolders); loose files go straight into `into`. Textures and .mtl files dropped with a
 * model are used for it.
 */
export async function importDropped(files: DroppedFile[], into: string, onStatus: (message: string | null) => void): Promise<ImportReport> {
    const report: ImportReport = { added: 0, failed: [], notes: [] };
    const models = files.filter((f) => isModelFile(f.path));
    if (!models.length) {
        report.failed.push({ name: files.length === 1 ? files[0].path : `${files.length} files`, error: `no 3D files in what was dropped (${SUPPORTED_FORMATS_TEXT})` });
        onStatus(null);
        return report;
    }
    const urls = new Map<DroppedFile, string>();
    const urlOf = (f: DroppedFile) => {
        let u = urls.get(f);
        if (!u) urls.set(f, (u = URL.createObjectURL(f.file)));
        return u;
    };
    const resources = files.filter((f) => isResourceFile(f.path));
    try {
        for (const [i, model] of models.entries()) {
            const ext = extOf(model.path);
            const name = stripExt(model.path);
            const dir = parentFolder(model.path);
            const folder = joinFolder(into, dir);
            const status = (m: string) => onStatus(models.length > 1 ? `${m} (${i + 1} of ${models.length})` : m);
            try {
                let glb: Uint8Array;
                let notes: string[] = [];
                if (ext === "glb") {
                    glb = new Uint8Array(await model.file.arrayBuffer());
                } else {
                    const { convertToGlb } = await import("../three/convert");
                    const source: ImportSource = {
                        id: `drop-${i}`,
                        name,
                        ext,
                        url: urlOf(model),
                        path: model.path,
                        // Paths relative to the model's folder when inside it; others are found by name.
                        resources: resources.map((r) => ({ name: dir && r.path.startsWith(`${dir}/`) ? r.path.slice(dir.length + 1) : r.path, url: urlOf(r), path: r.path })),
                    };
                    const result = await convertToGlb(source, async (url) => new Uint8Array(await (await fetch(url)).arrayBuffer()), status);
                    glb = result.glb;
                    notes = result.notes;
                }
                status(`Adding ${name} to the library`);
                await bridge().call("library.addModel", { name, glbBase64: bytesToBase64(glb), sourceFormat: ext, folder, from: `drag and drop: ${model.path}`, notes });
                report.added++;
                if (notes.length) report.notes.push(`${baseName(model.path)}: ${notes.join("; ")}`);
            } catch (err) {
                report.failed.push({ name: baseName(model.path), error: (err as Error).message || String(err) });
            }
        }
    } finally {
        for (const u of urls.values()) URL.revokeObjectURL(u);
        onStatus(null);
    }
    return report;
}

/** One line for a toast. */
export function describeReport(report: ImportReport): { kind: "success" | "error" | "info"; message: string } | null {
    const { added, failed, notes } = report;
    if (!added && !failed.length) return null;
    const parts: string[] = [];
    if (added) parts.push(`Added ${added} model${added === 1 ? "" : "s"} to the library.`);
    if (failed.length) parts.push(`Could not import ${failed.map((f) => `${f.name} (${f.error})`).join(", ")}.`);
    if (notes.length) parts.push(notes.join(" "));
    return { kind: failed.length && !added ? "error" : failed.length || notes.length ? "info" : "success", message: parts.join(" ") };
}
