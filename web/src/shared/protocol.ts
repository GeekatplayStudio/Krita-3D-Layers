/**
 * The bridge between the WebView UI and the UXP host.
 *
 * UXP gives a WebView exactly one channel: `webview.postMessage(obj)` towards the
 * page and `window.uxpHost.postMessage(obj)` back, with JSON-serialised payloads.
 * On top of that this file defines a tiny request/response protocol:
 *
 *   page → host   { t: "req", id, method, params }
 *   host → page   { t: "res", id, ok: true, result } | { t: "res", id, ok: false, error }
 *   host → page   { t: "evt", name, data }            (push notifications)
 *
 * `HostApi` lists every method with its params and result types; both sides are
 * type-checked against it. Binary data (renders, thumbnails) travels as base64
 * strings — measured at ~50 MB/s through the bridge, far below any real cost.
 */
import type {
    AppInfo,
    Job,
    LayerState,
    LibraryItem,
    PlaceResult,
    ProviderId,
    ProviderStatus,
    ProviderTestResult,
    PsContext,
    RemotePage,
    SendSource,
    UpdateInfo,
} from "./types";
import type { DeepPartial, EditorViewPrefs, PublicSettings, SecretKey, Settings } from "./settings";
import type { ImportBatch } from "./modelFormats";
import type { LightingDefaults, ThreeDSettings } from "./threeD";
import type { Box } from "./placement";

export type LogLevel = "debug" | "info" | "warn" | "error";

/** Data the 3D editor page needs to start. */
export type EditorInit = {
    mode: "new" | "update";
    model: {
        libraryId: string;
        name: string;
        /** URL the editor can load directly, or null when it must call `library.readFile`. */
        url: string | null;
        file: string;
        sizeBytes: number;
    };
    settings: ThreeDSettings;
    lighting: LightingDefaults;
    rememberLighting: boolean;
    /** Size of the target document, used to suggest an export resolution. */
    document?: { title: string; width: number; height: number };
    /** "Show document" and the layers-above options, as last used. */
    view: EditorViewPrefs;
};

/** A composite of some of the document's layers (PNG, scaled down to at most 2048 px). */
export type DocumentImage = { pngBase64: string; width: number; height: number };

/** The document around the 3D layer, for "Show document" in the editor. */
export type DocumentView = {
    title: string;
    /** Document size in pixels. */
    width: number;
    height: number;
    /** The visible layers under the 3D layer (or under where a new one goes); null when there are none. */
    below: DocumentImage | null;
    /** The visible layers above it; null when there are none. */
    above: DocumentImage | null;
    /** Where the edited 3D layer's render sits in the document (its smart object frame). */
    frame?: Box;
};

/** What the editor sends back when the user clicks OK. */
export type EditorResult = {
    pngBase64: string;
    width: number;
    height: number;
    settings: ThreeDSettings;
    /** Bounding box of non-transparent pixels in the render (for fitting to a source area). */
    contentBounds?: { left: number; top: number; right: number; bottom: number };
    /**
     * Where the whole render goes in the document (document pixels). Set when the editor
     * showed the document, so the layer lands exactly where the model was seen.
     */
    frame?: Box;
};

export type HostApi = {
    "app.info": [void, AppInfo];

    "settings.get": [void, PublicSettings];
    "settings.update": [DeepPartial<Settings>, PublicSettings];
    "settings.setSecret": [{ key: SecretKey; value: string }, PublicSettings];
    "settings.reset": [void, PublicSettings];
    "settings.pickWorkflow": [void, PublicSettings | null];

    "providers.status": [void, ProviderStatus[]];
    "providers.test": [{ providerId: ProviderId }, ProviderTestResult];

    "ps.context": [void, PsContext];
    "ps.sourcePreview": [{ source: SendSource }, { dataUrl: string; width: number; height: number; label: string } | null];

    "generate.start": [{ providerId: ProviderId; source: SendSource; name?: string }, Job];

    "jobs.list": [void, Job[]];
    "jobs.cancel": [{ id: string }, Job];
    "jobs.retry": [{ id: string }, Job];
    "jobs.dismiss": [{ id: string }, void];
    "jobs.recover": [{ providerId: ProviderId; remoteId: string; name?: string }, Job];

    "remote.list": [{ providerId: ProviderId; page: number; pageSize: number }, RemotePage];
    "remote.import": [{ providerId: ProviderId; remoteId: string; name?: string }, LibraryItem];

    "library.list": [void, LibraryItem[]];
    "library.update": [{ id: string; name?: string; favorite?: boolean }, LibraryItem];
    "library.remove": [{ id: string }, void];
    /** Deletes several models (and their files). */
    "library.removeMany": [{ ids: string[] }, void];
    /** Adds the sample model that ships with the plugin (try posing without a 3D service). */
    "library.addSample": [void, LibraryItem];
    /** Moves models into a library folder ("" = top level). */
    "library.move": [{ ids: string[]; folder: string }, void];
    /** Every library folder ("A", "A/B", …). Folders are virtual; see shared/libraryFolders.ts. */
    "library.folders": [void, string[]];
    "library.createFolder": [{ parent: string; name: string }, string[]];
    "library.renameFolder": [{ path: string; name: string }, string[]];
    /** Deletes a folder; its models and subfolders move to its parent. */
    "library.deleteFolder": [{ path: string }, string[]];
    /** Adds a model the panel read itself (drag and drop), already GLB or converted to GLB. */
    "library.addModel": [{ name: string; glbBase64: string; sourceFormat: string; folder?: string; from?: string; notes?: string[] }, LibraryItem];
    /** Lets the user pick model files (or a folder of them); GLB is stored now, the rest comes back for conversion. null = cancelled. */
    "library.pickImport": [{ pickFolder?: boolean; into?: string }, ImportBatch | null];
    /** Imports new files from the library's Import folder (files copied there in the file manager). */
    "library.scanInbox": [void, ImportBatch];
    /** Reads a file that belongs to an import (fallback when the WebView cannot read it itself). */
    "library.readImportFile": [{ id: string; path: string }, { base64: string }];
    /** Stores a model the panel converted to GLB. */
    "library.addConverted": [{ id: string; name: string; glbBase64: string; sourceFormat: string; notes?: string[] }, LibraryItem];
    /** Records that converting an import failed (logged; an Import-folder file is not retried). */
    "library.importFailed": [{ id: string; error: string }, void];
    "library.saveThumbnail": [{ id: string; pngBase64: string }, LibraryItem];
    "library.readFile": [{ file: string }, { base64: string }];
    "library.revealFolder": [void, void];
    "library.revealInbox": [void, void];

    /** Opens the modal 3D editor for a library model and places the result in the active document. */
    "editor.placeModel": [{ libraryId: string; atSource?: string }, PlaceResult | null];
    /** Opens the modal 3D editor for the active 3D layer and updates it on OK. */
    "editor.editActiveLayer": [void, PlaceResult | null];
    "layer.state": [void, LayerState | null];
    "layer.detach3D": [void, void];

    /* --- only called by the editor page inside the modal dialog --- */
    "editor.getInit": [void, EditorInit];
    "editor.complete": [EditorResult, void];
    "editor.cancel": [void, void];
    "editor.rememberLighting": [LightingDefaults, void];
    /** The document's layers below and above the 3D layer (read once per editor session). */
    "editor.documentView": [void, DocumentView | null];
    "editor.rememberView": [EditorViewPrefs, void];

    "update.check": [{ force?: boolean }, UpdateInfo];
    "update.install": [void, { started: boolean; message: string }];
    "update.skip": [{ version: string }, void];

    "shell.openExternal": [{ url: string }, void];
    /** Text on the system clipboard (Ctrl/Cmd+V does not reach inputs in a docked panel: Photoshop takes it). */
    "clipboard.readText": [void, string];
    "log.write": [{ level: LogLevel; message: string; data?: unknown }, void];
    "log.tail": [{ lines: number }, string];
    "log.reveal": [void, void];
};

export type HostMethod = keyof HostApi;
export type ParamsOf<M extends HostMethod> = HostApi[M][0];
export type ResultOf<M extends HostMethod> = HostApi[M][1];

/** Push notifications from the host. */
export type HostEvents = {
    "jobs.changed": Job[];
    "library.changed": LibraryItem[];
    "library.foldersChanged": string[];
    "ps.context": PsContext;
    "settings.changed": PublicSettings;
    "update.available": UpdateInfo;
    "theme.changed": { theme: string };
    "toast": { kind: "info" | "success" | "error"; message: string };
};
export type HostEventName = keyof HostEvents;

export type RequestMessage = { t: "req"; id: number; method: HostMethod; params: unknown };
export type ResponseMessage =
    | { t: "res"; id: number; ok: true; result: unknown }
    | { t: "res"; id: number; ok: false; error: { message: string; code?: string } };
export type EventMessage = { t: "evt"; name: HostEventName; data: unknown };
export type BridgeMessage = RequestMessage | ResponseMessage | EventMessage;

export function isBridgeMessage(value: unknown): value is BridgeMessage {
    if (!value || typeof value !== "object") return false;
    const t = (value as { t?: unknown }).t;
    return t === "req" || t === "res" || t === "evt";
}
