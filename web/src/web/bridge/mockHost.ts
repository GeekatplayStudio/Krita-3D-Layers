/**
 * A fake UXP host for running the UI in a normal browser (`npm run dev:web`) and in
 * Playwright tests. It implements the same HostApi with in-memory state and the
 * sample model in tests/fixtures/public/samples. Nothing here ships in the plugin's
 * behaviour: inside Photoshop window.uxpHost exists and this module is never loaded.
 */
import type { DocumentImage, DocumentView, EditorInit, EditorResult, HostApi, HostEventName, HostMethod, RequestMessage } from "@shared/protocol";
import { DEFAULT_SETTINGS, SECRET_KEYS, mergeSettings, secretPreview, type PublicSettings, type SecretKey, type Settings } from "@shared/settings";
import { settingsForNewModel } from "@shared/threeD";
import { PROVIDER_IDS, PROVIDER_LABELS, type AppInfo, type Job, type LibraryItem, type ProviderId, type PsContext, type RemoteItem } from "@shared/types";
import { base64ToBytes } from "@shared/bytes";
import type { ImportSource } from "@shared/modelFormats";
import { allFolders, cleanFolderName, joinFolder, normalizeFolder, parentFolder, relocateFolder, withAncestors } from "@shared/libraryFolders";
import type { Transport } from "./client";

type Handler = (params: unknown) => unknown;

declare global {
    interface Window {
        /** Last editor result, for tests. */
        __ps3dEditorResult?: EditorResult | null;
        /** Models converted by the import, for tests. */
        __ps3dImported?: { name: string; sourceFormat: string; bytes: number; notes: string[]; images?: number; meshes?: number; folder?: string }[];
    }
}

export function createMockTransport(): Transport {
    const listeners: ((m: unknown) => void)[] = [];
    const emit = (name: HostEventName, data: unknown) => listeners.forEach((fn) => fn({ t: "evt", name, data }));

    let settings: Settings = mergeSettings(DEFAULT_SETTINGS, {});
    const secrets: Partial<Record<SecretKey, string>> = { "meshy.apiKey": "msy_mock_key_1234" };
    const publicSettings = (): PublicSettings => ({
        ...settings,
        secrets: Object.fromEntries(SECRET_KEYS.map((k) => [k, { set: !!secrets[k], preview: secretPreview(secrets[k] ?? "") }])) as PublicSettings["secrets"],
    });

    const now = Date.now();
    let library: LibraryItem[] = [
        { id: "lib_totem", name: "Totem (sample)", origin: "local", modelFile: "samples/totem.glb", format: "glb", sizeBytes: 6880, createdAt: now - 86_400_000, importedAt: now - 86_400_000 },
        { id: "lib_totem2", name: "Meshy totem", origin: "meshy", remoteId: "018f-mock", modelFile: "samples/totem.glb", thumbFile: "samples/totem-thumb.png", format: "glb", sizeBytes: 6880, createdAt: now - 3_600_000, importedAt: now - 3_600_000, favorite: true },
    ];
    let storedFolders = new Set<string>();
    // ?demo=1: a library of the demo models (scripts/make-demo-models.py), for screenshots.
    if (new URLSearchParams(location.search).get("demo")) {
        const demo = (id: string, name: string, file: string, origin: LibraryItem["origin"], folder?: string, favorite?: boolean): LibraryItem => ({ id, name, origin, modelFile: `samples/demo/${file}.glb`, format: "glb", sizeBytes: 100_000, createdAt: now, importedAt: now - library.length * 60_000, folder, favorite });
        library = [
            demo("lib_rocket", "Toy rocket", "rocket", "meshy", undefined, true),
            demo("lib_vase", "Ceramic vase", "vase", "tripo"),
            demo("lib_mushroom", "Mushroom", "mushroom", "comfyui"),
            demo("lib_vase2", "Vase, glazed", "vase", "local", "Props"),
            demo("lib_mush2", "Mushroom, tall", "mushroom", "hitem3d", "Props"),
            { ...library[0], id: "lib_totem_demo", name: "Totem" },
        ];
        storedFolders = new Set(["Props", "Characters"]);
    }
    let importTarget = "";
    const folders = () => allFolders(storedFolders, library);
    const libraryChanged = () => {
        emit("library.changed", [...library]);
        emit("library.foldersChanged", folders());
    };
    let jobs: Job[] = [];
    const ctx: PsContext = { hasDocument: true, docId: 1, docTitle: "Mock.psd", docWidth: 1920, docHeight: 1080, layerId: 2, layerName: "Chair", layerKind: "pixel", hasSelection: false, is3DLayer: false };
    // ?layer3d=<name>: the active layer is a 3D layer (for screenshots of the "Edit pose & light" banner).
    const layer3d = new URLSearchParams(location.search).get("layer3d");
    if (layer3d) Object.assign(ctx, { layerName: `${layer3d} (3D)`, layerKind: "smartObject", is3DLayer: true, modelName: layer3d });

    const info: AppInfo = {
        pluginId: "com.geekatplay.photoshop3d",
        pluginVersion: "0.0.0-dev",
        hostName: "Browser (mock host)",
        hostVersion: "-",
        uxpVersion: "-",
        platform: navigator.platform,
        dataFolder: "(mock)",
        libraryFolder: "(mock)/library",
        importFolder: "(mock)/library/Import",
        logFile: "(mock)/logs/photoshop3d.log",
        libraryBaseUrl: "./",
        repoUrl: "https://github.com/GeekatplayStudio/Photoshop-3D",
        theme: "dark",
        credentialsFile: "(mock)/credentials.json",
        buildStamp: "dev",
        channel: new URLSearchParams(location.search).get("channel") === "marketplace" ? "marketplace" : "github",
    };

    const editorInit = (libraryId: string): EditorInit => {
        const item = library.find((i) => i.id === libraryId) ?? library[0];
        // ?mode=update and ?name=… let the docs screenshots show the re-pose dialog.
        const query = new URLSearchParams(location.search);
        return {
            mode: query.get("mode") === "update" ? "update" : "new",
            model: { libraryId: item.id, name: query.get("name") ?? item.name, url: `./${item.modelFile}`, file: item.modelFile, sizeBytes: item.sizeBytes },
            settings: settingsForNewModel(settings.editor.lighting, 1024),
            lighting: settings.editor.lighting,
            rememberLighting: true,
            document: { title: "Mock.psd", width: 1920, height: 1080 },
            view: settings.editor.view,
        };
    };

    // "Show document": a drawn landscape below the 3D layer and grass in front of it, or with
    // ?scene=desk the desk scene rendered by scripts/make-demo-scene.py (for screenshots).
    const documentView = async (): Promise<DocumentView> => {
        const W = 1920;
        const H = 1080;
        const image = (draw: (g: CanvasRenderingContext2D) => void): DocumentImage => {
            const canvas = document.createElement("canvas");
            canvas.width = W;
            canvas.height = H;
            draw(canvas.getContext("2d")!);
            return { pngBase64: canvas.toDataURL("image/png").replace(/^data:[^,]*,/, ""), width: W, height: H };
        };
        const update = new URLSearchParams(location.search).get("mode") === "update";
        const frame = update ? { left: 660, top: 300, right: 1260, bottom: 900 } : undefined;
        if (new URLSearchParams(location.search).get("scene") === "desk") {
            const load = async (file: string) => {
                const img = new Image();
                img.src = `./samples/demo/${file}`;
                await img.decode();
                return image((g) => g.drawImage(img, 0, 0, W, H));
            };
            return { title: "Desk.psd", width: W, height: H, below: await load("scene-below.jpg"), above: await load("scene-above.png"), frame };
        }
        const below = image((g) => {
            const sky = g.createLinearGradient(0, 0, 0, H * 0.62);
            sky.addColorStop(0, "#5b8fc7");
            sky.addColorStop(1, "#f2c99a");
            g.fillStyle = sky;
            g.fillRect(0, 0, W, H);
            g.fillStyle = "#fff4d6";
            g.beginPath();
            g.arc(W * 0.78, H * 0.3, 70, 0, Math.PI * 2);
            g.fill();
            const hill = (y: number, amp: number, color: string) => {
                g.fillStyle = color;
                g.beginPath();
                g.moveTo(0, H);
                for (let x = 0; x <= W; x += 20) g.lineTo(x, y + Math.sin(x / 260) * amp + Math.sin(x / 97) * amp * 0.3);
                g.lineTo(W, H);
                g.fill();
            };
            hill(H * 0.55, 40, "#8a9fb3");
            hill(H * 0.62, 30, "#6f8a5e");
            const ground = g.createLinearGradient(0, H * 0.66, 0, H);
            ground.addColorStop(0, "#9b8a63");
            ground.addColorStop(1, "#5e4f36");
            g.fillStyle = ground;
            g.fillRect(0, H * 0.68, W, H);
        });
        const above = image((g) => {
            g.strokeStyle = "#2f4a22";
            g.lineCap = "round";
            for (let i = 0; i < 260; i++) {
                const x = (i * 7919) % W;
                const h = 40 + ((i * 104729) % 120);
                g.lineWidth = 4 + (i % 4);
                g.beginPath();
                g.moveTo(x, H);
                g.quadraticCurveTo(x + 10, H - h / 2, x + ((i % 7) - 3) * 9, H - h);
                g.stroke();
            }
        });
        return { title: "Mock.psd", width: W, height: H, below, above, frame };
    };

    const runJob = (job: Job) => {
        const timer = setInterval(() => {
            job.progress = Math.min(100, job.progress + 20);
            job.status = job.progress >= 100 ? "succeeded" : "running";
            job.message = job.progress >= 100 ? "Ready in library" : `${PROVIDER_LABELS[job.providerId]} is generating`;
            job.updatedAt = Date.now();
            if (job.status === "succeeded") {
                clearInterval(timer);
                const item: LibraryItem = { ...library[0], id: `lib_${job.id}`, name: job.name, origin: job.providerId, remoteId: job.remoteId, importedAt: Date.now() };
                library = [item, ...library];
                job.libraryId = item.id;
                emit("library.changed", library);
            }
            emit("jobs.changed", [...jobs]);
        }, 700);
    };

    const handlers: { [M in HostMethod]?: (p: HostApi[M][0]) => HostApi[M][1] | Promise<HostApi[M][1]> } = {
        "app.info": () => info,
        "settings.get": () => publicSettings(),
        "settings.update": (patch) => {
            settings = mergeSettings(settings, patch);
            emit("settings.changed", publicSettings());
            return publicSettings();
        },
        "settings.setSecret": ({ key, value }) => {
            secrets[key] = value;
            return publicSettings();
        },
        "settings.reset": () => {
            settings = mergeSettings(DEFAULT_SETTINGS, {});
            return publicSettings();
        },
        "settings.pickWorkflow": () => null,
        "providers.status": () =>
            PROVIDER_IDS.map((id) => ({
                id,
                label: PROVIDER_LABELS[id],
                configured: id === "comfyui" || !!secrets[(id === "hitem3d" ? "hitem3d.accessKey" : `${id}.apiKey`) as SecretKey],
                hint: id === "comfyui" ? undefined : "Add your API key in Settings.",
                capabilities: { generate: true, browse: true, cancel: id !== "tripo" },
            })),
        "providers.test": ({ providerId }) => ({ ok: true, message: `Connected to ${PROVIDER_LABELS[providerId]}.`, balance: "1000 credits" }),
        "ps.context": () => ctx,
        "ps.sourcePreview": () => ({ dataUrl: "./samples/totem-thumb.png", width: 256, height: 256, label: "Chair" }),
        "generate.start": ({ providerId, name }) => {
            const job: Job = {
                id: `job_${Date.now().toString(36)}`,
                providerId,
                remoteId: `mock-${Math.random().toString(36).slice(2, 8)}`,
                name: name || "Chair",
                status: "running",
                progress: 0,
                message: "Submitted",
                createdAt: Date.now(),
                updatedAt: Date.now(),
                sourcePreview: "./samples/totem-thumb.png",
            };
            jobs = [job, ...jobs];
            emit("jobs.changed", [...jobs]);
            runJob(job);
            return job;
        },
        "jobs.list": () => jobs,
        "jobs.cancel": ({ id }) => {
            const j = jobs.find((x) => x.id === id)!;
            j.status = "cancelled";
            emit("jobs.changed", [...jobs]);
            return j;
        },
        "jobs.retry": ({ id }) => jobs.find((x) => x.id === id)!,
        "jobs.dismiss": ({ id }) => {
            jobs = jobs.filter((j) => j.id !== id);
            emit("jobs.changed", [...jobs]);
        },
        "jobs.recover": ({ providerId, remoteId }) => {
            const job: Job = { id: `job_${Date.now().toString(36)}`, providerId, remoteId, name: `Task ${remoteId}`, status: "running", progress: 0, createdAt: Date.now(), updatedAt: Date.now() };
            jobs = [job, ...jobs];
            runJob(job);
            return job;
        },
        "remote.list": ({ providerId, page }) => {
            const items: RemoteItem[] = Array.from({ length: 6 }, (_, i) => ({
                providerId: providerId as ProviderId,
                remoteId: `${providerId}-${page}-${i}`,
                name: `${PROVIDER_LABELS[providerId]} model ${(page - 1) * 6 + i + 1}`,
                status: i === 4 ? "running" : i === 5 ? "failed" : "succeeded",
                progress: i === 4 ? 40 : undefined,
                createdAt: Date.now() - i * 3_600_000,
                thumbnailUrl: i % 2 ? "./samples/totem-thumb.png" : undefined,
                hasModel: i < 4,
                libraryId: i === 0 ? "lib_totem2" : undefined,
            }));
            return { items, page, hasMore: page < 3, notice: providerId === "hitem3d" ? "Mock: Hitem3D has no list API." : undefined };
        },
        "remote.import": ({ providerId, remoteId, name }) => {
            const item: LibraryItem = { ...library[0], id: `lib_${remoteId}`, name: name ?? remoteId, origin: providerId, remoteId, importedAt: Date.now() };
            library = [item, ...library];
            emit("library.changed", library);
            return item;
        },
        "library.list": () => library,
        "library.update": ({ id, name, favorite }) => {
            const item = library.find((i) => i.id === id)!;
            if (name) item.name = name;
            if (favorite !== undefined) item.favorite = favorite;
            emit("library.changed", [...library]);
            return item;
        },
        "library.remove": ({ id }) => {
            library = library.filter((i) => i.id !== id);
            libraryChanged();
        },
        "library.removeMany": ({ ids }) => {
            for (const i of library) if (ids.includes(i.id) && i.folder) withAncestors(i.folder).forEach((a) => storedFolders.add(a));
            library = library.filter((i) => !ids.includes(i.id));
            libraryChanged();
        },
        "library.move": ({ ids, folder }) => {
            const target = normalizeFolder(folder);
            library = library.map((i) => (ids.includes(i.id) ? { ...i, folder: target || undefined } : i));
            withAncestors(target).forEach((a) => storedFolders.add(a));
            libraryChanged();
        },
        "library.folders": () => folders(),
        "library.addSample": () => {
            const item: LibraryItem = { id: `lib_sample_${library.length}`, name: "Sample rocket", origin: "local", modelFile: "samples/demo/rocket.glb", format: "glb", sizeBytes: 104800, createdAt: Date.now(), importedAt: Date.now(), meta: { sample: true } };
            library = [item, ...library];
            libraryChanged();
            return item;
        },
        "library.createFolder": ({ parent, name }) => {
            const clean = cleanFolderName(name);
            if (!clean) throw new Error("Type a folder name.");
            const path = joinFolder(parent, clean);
            if (folders().some((f) => f.toLowerCase() === path.toLowerCase())) throw new Error(`There is already a folder named "${clean}" here.`);
            withAncestors(path).forEach((a) => storedFolders.add(a));
            libraryChanged();
            return folders();
        },
        "library.renameFolder": ({ path, name }) => {
            const to = joinFolder(parentFolder(path), cleanFolderName(name));
            if (!cleanFolderName(name)) throw new Error("Type a folder name.");
            if (to !== path && folders().some((f) => f.toLowerCase() === to.toLowerCase())) throw new Error(`There is already a folder named "${cleanFolderName(name)}" here.`);
            library = library.map((i) => ({ ...i }));
            storedFolders = relocateFolder(storedFolders, library, path, to);
            libraryChanged();
            return folders();
        },
        "library.deleteFolder": ({ path }) => {
            library = library.map((i) => ({ ...i }));
            storedFolders = relocateFolder(storedFolders, library, path, parentFolder(path));
            libraryChanged();
            return folders();
        },
        "library.addModel": ({ name, glbBase64, sourceFormat, folder, notes }) => {
            const glb = base64ToBytes(glbBase64);
            const url = URL.createObjectURL(new Blob([glb as BlobPart], { type: "model/gltf-binary" }));
            const item: LibraryItem = { id: `lib_drop_${Date.now().toString(36)}_${library.length}`, name, origin: "local", modelFile: url, format: "glb", folder: normalizeFolder(folder) || undefined, sizeBytes: glb.byteLength, createdAt: Date.now(), importedAt: Date.now(), meta: { sourceFormat, notes } };
            (window.__ps3dImported ??= []).push({ name, sourceFormat, bytes: glb.byteLength, notes: notes ?? [], folder: item.folder ?? "" });
            library = [item, ...library];
            libraryChanged();
            return item;
        },
        // Import: the files in tests/fixtures/public/samples/import, as the host would describe them.
        "library.pickImport": ({ into }) => {
            importTarget = normalizeFolder(into);
            const dir = "./samples/import/";
            const resources = ["cube.mtl", "cube.bin", "textures/checker.png"].map((name) => ({ name, url: `${dir}${name}`, path: `${dir}${name}` }));
            const toConvert: ImportSource[] = ["fbx", "obj", "gltf", "stl", "ply", "usdz"].map((ext) => ({ id: `imp_${ext}`, name: `cube-${ext}`, ext, url: `${dir}cube.${ext}`, path: `${dir}cube.${ext}`, resources }));
            return { imported: [], toConvert, failed: [{ name: "notes.txt", error: "not a supported 3D file" }] };
        },
        "library.scanInbox": () => ({ imported: [], toConvert: [], failed: [] }),
        "library.readImportFile": async ({ path }) => {
            const buf = new Uint8Array(await (await fetch(path)).arrayBuffer());
            let s = "";
            for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
            return { base64: btoa(s) };
        },
        "library.addConverted": ({ id, name, glbBase64, sourceFormat, notes }) => {
            const glb = base64ToBytes(glbBase64);
            const url = URL.createObjectURL(new Blob([glb as BlobPart], { type: "model/gltf-binary" }));
            const item: LibraryItem = { id: `lib_${id}`, name, origin: "local", modelFile: url, format: "glb", folder: importTarget || undefined, sizeBytes: glb.byteLength, createdAt: Date.now(), importedAt: Date.now(), meta: { sourceFormat, convertedToGlb: true, notes } };
            const jsonLength = new DataView(glb.buffer, glb.byteOffset).getUint32(12, true);
            const json = JSON.parse(new TextDecoder().decode(glb.subarray(20, 20 + jsonLength))) as { images?: unknown[]; meshes?: unknown[] };
            (window.__ps3dImported ??= []).push({ name, sourceFormat, bytes: glb.byteLength, notes: notes ?? [], images: json.images?.length ?? 0, meshes: json.meshes?.length ?? 0 });
            library = [item, ...library];
            libraryChanged();
            return item;
        },
        "library.importFailed": ({ id, error }) => {
            (window.__ps3dImported ??= []).push({ name: id, sourceFormat: "failed", bytes: 0, notes: [error] });
        },
        "library.revealInbox": () => undefined,
        "library.saveThumbnail": ({ id, pngBase64 }) => {
            const item = library.find((i) => i.id === id)!;
            item.thumbFile = `data:image/png;base64,${pngBase64}`;
            emit("library.changed", [...library]);
            return item;
        },
        "library.readFile": async ({ file }) => {
            const buf = new Uint8Array(await (await fetch(`./${file}`)).arrayBuffer());
            let s = "";
            for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
            return { base64: btoa(s) };
        },
        "library.revealFolder": () => undefined,
        "editor.placeModel": ({ libraryId }) => {
            window.open(`./editor.html?model=${encodeURIComponent(libraryId)}`, "_blank", "width=1200,height=800");
            return null;
        },
        "editor.editActiveLayer": () => null,
        "layer.state": () => null,
        "layer.detach3D": () => undefined,
        "editor.getInit": () => editorInit(new URLSearchParams(location.search).get("model") ?? "lib_totem"),
        "editor.complete": (result) => {
            window.__ps3dEditorResult = result;
        },
        "editor.cancel": () => {
            window.__ps3dEditorResult = null;
        },
        "editor.rememberLighting": (lighting) => {
            settings = mergeSettings(settings, { editor: { lighting } });
        },
        "editor.documentView": () => documentView(),
        "editor.rememberView": (view) => {
            settings = mergeSettings(settings, { editor: { view } });
        },
        "update.check": () => (info.channel === "marketplace" ? { currentVersion: "0.0.0-dev", available: false, checkedAt: 0 } : { currentVersion: "0.0.0-dev", latestVersion: "0.1.0", available: true, releaseName: "v0.1.0", releaseNotes: "Mock release notes", releaseUrl: "https://github.com/GeekatplayStudio/Photoshop-3D/releases", checkedAt: Date.now() }),
        "update.install": () => ({ started: false, message: "Mock host: nothing to install." }),
        "update.skip": () => undefined,
        "shell.openExternal": ({ url }) => {
            window.open(url, "_blank");
        },
        "clipboard.readText": () => navigator.clipboard.readText(),
        "log.write": ({ level, message, data }) => {
            console[level === "debug" ? "log" : level](`[mock host] ${message}`, data ?? "");
        },
        "log.tail": () => "mock log line 1\nmock log line 2",
        "log.reveal": () => undefined,
    };

    return {
        send(message) {
            const req = message as RequestMessage;
            const handler = handlers[req.method] as Handler | undefined;
            setTimeout(async () => {
                try {
                    if (!handler) throw new Error(`Mock host has no ${req.method}`);
                    const result = await handler(req.params);
                    listeners.forEach((fn) => fn({ t: "res", id: req.id, ok: true, result: result ?? null }));
                } catch (err) {
                    listeners.forEach((fn) => fn({ t: "res", id: req.id, ok: false, error: { message: (err as Error).message } }));
                }
            }, 30);
        },
        onMessage(fn) {
            listeners.push(fn);
        },
    };
}
