/**
 * Domain types shared by the UXP host and the WebView UI.
 * Everything that crosses the bridge is plain JSON built from these types.
 */
import type { ThreeDSettings } from "./threeD";

export type ProviderId = "meshy" | "tripo" | "hitem3d" | "comfyui";
export const PROVIDER_IDS: readonly ProviderId[] = ["meshy", "tripo", "hitem3d", "comfyui"];

/** Where a library model came from: a provider, or a file the user imported. */
export type ModelOrigin = ProviderId | "local";

export const PROVIDER_LABELS: Record<ModelOrigin, string> = {
    meshy: "Meshy",
    tripo: "Tripo",
    hitem3d: "Hitem3D",
    comfyui: "ComfyUI (local)",
    local: "Imported file",
};

/* ------------------------------------------------------------------ jobs */

export type JobStatus = "queued" | "submitting" | "running" | "downloading" | "succeeded" | "failed" | "cancelled";

export const ACTIVE_JOB_STATUSES: readonly JobStatus[] = ["queued", "submitting", "running", "downloading"];

/** Where a generation's source pixels came from, so the result can be placed back there. */
export type SourceTarget = {
    docId: number;
    docTitle: string;
    layerId?: number;
    /** Document pixel bounds of the source. */
    bounds: { left: number; top: number; right: number; bottom: number };
};

export type Job = {
    id: string;
    providerId: ProviderId;
    /** Provider task id (Meshy/Tripo/Hitem3D task id, ComfyUI prompt id). */
    remoteId?: string;
    name: string;
    status: JobStatus;
    /** 0-100. */
    progress: number;
    message?: string;
    error?: string;
    createdAt: number;
    updatedAt: number;
    /** Library entry created when the result was downloaded. */
    libraryId?: string;
    /** Small data-URL preview of the image that was sent. */
    sourcePreview?: string;
    source?: SourceTarget;
    /** Provider-specific state needed to keep polling after a restart (endpoint kind, etc). */
    meta?: Record<string, unknown>;
    /** Polling bookkeeping (host only). */
    nextPollAt?: number;
    pollDelayMs?: number;
    pollErrors?: number;
};

/* --------------------------------------------------------------- library */

export type LibraryItem = {
    id: string;
    name: string;
    origin: ModelOrigin;
    /** Provider task id, when the model came from a provider. */
    remoteId?: string;
    /** Library-relative path of the model file, e.g. "lib_x/model.glb". */
    modelFile: string;
    /** Library-relative path of the preview image. */
    thumbFile?: string;
    /** Library-relative path of the image that generated the model (if made here). */
    sourceFile?: string;
    format: "glb" | "gltf";
    /** Library folder ("Characters/Robots"); "" or absent = top level. See shared/libraryFolders.ts. */
    folder?: string;
    sizeBytes: number;
    createdAt: number;
    importedAt: number;
    favorite?: boolean;
    /** Free-form provider metadata kept for transparency (task JSON summary). */
    meta?: Record<string, unknown>;
};

/* -------------------------------------------------------- remote browse */

export type RemoteStatus = "succeeded" | "running" | "queued" | "failed" | "cancelled" | "expired" | "unknown";

export type RemoteItem = {
    providerId: ProviderId;
    remoteId: string;
    name: string;
    status: RemoteStatus;
    progress?: number;
    createdAt?: number;
    thumbnailUrl?: string;
    /** True when the task produced a downloadable model. */
    hasModel: boolean;
    /** Provider task kind, e.g. "image-to-3d". */
    kind?: string;
    /** Set by the host when this remote model is already in the local library. */
    libraryId?: string;
};

export type RemotePage = {
    items: RemoteItem[];
    page: number;
    hasMore: boolean;
    /** Shown when a provider cannot list everything (e.g. Tripo has no list API). */
    notice?: string;
};

/* ------------------------------------------------------------ providers */

export type ProviderCapabilities = {
    generate: boolean;
    browse: boolean;
    cancel: boolean;
};

export type ProviderStatus = {
    id: ProviderId;
    label: string;
    configured: boolean;
    capabilities: ProviderCapabilities;
    /** Why the provider is not usable yet ("Add your API key in Settings"). */
    hint?: string;
};

export type ProviderTestResult = {
    ok: boolean;
    message: string;
    /** Remaining credits/balance when the provider reports it. */
    balance?: string;
};

/* ------------------------------------------------------------ photoshop */

export type PsContext = {
    hasDocument: boolean;
    docId?: number;
    docTitle?: string;
    docWidth?: number;
    docHeight?: number;
    layerId?: number;
    layerName?: string;
    layerKind?: string;
    hasSelection: boolean;
    /** True when the active layer is a 3D layer made by this plugin. */
    is3DLayer: boolean;
    /** Model name stored on the active 3D layer. */
    modelName?: string;
};

export type SendSource = "auto" | "layer" | "selection";

/** What a placed 3D layer stores in its XMP so it can be re-posed later. */
export type LayerState = {
    v: 1;
    libraryId: string;
    modelName: string;
    origin: ModelOrigin;
    remoteId?: string;
    settings: ThreeDSettings;
    updatedAt: number;
};

export type PlaceResult = {
    docId: number;
    layerId: number;
    layerName: string;
    updated: boolean;
};

/* --------------------------------------------------------------- update */

export type UpdateInfo = {
    currentVersion: string;
    latestVersion?: string;
    available: boolean;
    releaseName?: string;
    releaseNotes?: string;
    releaseUrl?: string;
    downloadUrl?: string;
    publishedAt?: string;
    checkedAt: number;
    error?: string;
};

export type AppInfo = {
    pluginId: string;
    pluginVersion: string;
    hostName: string;
    hostVersion: string;
    uxpVersion: string;
    platform: string;
    dataFolder: string;
    libraryFolder: string;
    /** Folder whose model files are added to the library automatically (library/Import). */
    importFolder: string;
    logFile: string;
    /** URL prefix the WebView uses to load library files directly ("../library/"), or null when it must ask the host. */
    libraryBaseUrl: string | null;
    repoUrl: string;
    /** Photoshop UI theme: darkest | dark | light | lightest. */
    theme: string;
    /** The file holding API keys (in the shared user-data folder). */
    credentialsFile: string;
    buildStamp: string;
    /**
     * Where this copy comes from: "github" (installers / GitHub releases; updates itself) or
     * "marketplace" (Creative Cloud Marketplace; Creative Cloud updates it).
     */
    channel: "github" | "marketplace";
};
