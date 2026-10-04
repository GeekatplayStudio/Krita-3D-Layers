import type { LibraryItem } from "./types";

/**
 * 3D file formats the library imports.
 *
 * The library stores every model as GLB, because that is what the 3D editor, previews and
 * re-posing load. A .glb (or a self-contained .gltf) is stored as it is. Every other format
 * is converted to GLB in the panel's WebView with three.js' loaders and GLTFExporter, with
 * its textures and materials embedded (src/web/three/convert.ts).
 */

export type ModelFormat = {
    ext: string;
    label: string;
    /** Up axis of the format's usual authoring tools; Z-up models are turned upright. */
    zUp?: boolean;
};

export const MODEL_FORMATS: readonly ModelFormat[] = [
    { ext: "glb", label: "glTF binary" },
    { ext: "gltf", label: "glTF" },
    { ext: "fbx", label: "FBX" },
    { ext: "obj", label: "Wavefront OBJ" },
    { ext: "dae", label: "Collada" },
    { ext: "usdz", label: "USDZ" },
    { ext: "usd", label: "USD" },
    { ext: "usda", label: "USD (text)" },
    { ext: "usdc", label: "USD (binary)" },
    { ext: "3ds", label: "3D Studio" },
    { ext: "stl", label: "STL", zUp: true },
    { ext: "ply", label: "PLY" },
    { ext: "3mf", label: "3MF", zUp: true },
    { ext: "amf", label: "AMF", zUp: true },
    { ext: "wrl", label: "VRML" },
    { ext: "vox", label: "MagicaVoxel", zUp: true },
];

export const MODEL_EXTENSIONS: readonly string[] = MODEL_FORMATS.map((f) => f.ext);

/**
 * Files a model can reference: materials, buffers and textures. When a model is imported,
 * these are collected from its folder (and subfolders) so its textures come along.
 */
export const RESOURCE_EXTENSIONS: readonly string[] = ["mtl", "bin", "png", "jpg", "jpeg", "tga", "bmp", "gif", "webp", "tif", "tiff"];

/** Lower-case extension without the dot ("" when there is none). */
export const extOf = (name: string): string => {
    const base = name.split(/[\\/]/).pop() ?? name;
    const dot = base.lastIndexOf(".");
    return dot > 0 ? base.slice(dot + 1).toLowerCase() : "";
};

export const baseName = (path: string): string => path.split(/[\\/]/).pop() ?? path;
export const stripExt = (name: string): string => baseName(name).replace(/\.[^.]+$/, "");

export const isModelFile = (name: string) => MODEL_EXTENSIONS.includes(extOf(name));
export const isResourceFile = (name: string) => RESOURCE_EXTENSIONS.includes(extOf(name));
export const formatOf = (name: string): ModelFormat | undefined => MODEL_FORMATS.find((f) => f.ext === extOf(name));

/** "GLB, glTF, FBX, OBJ, …" for hints and dialogs. */
export const SUPPORTED_FORMATS_TEXT = MODEL_FORMATS.filter((f) => !["usda", "usdc"].includes(f.ext))
    .map((f) => f.ext.toUpperCase())
    .join(", ");

/**
 * True when a .gltf carries all its buffers and images inline (data: URIs), so it can be
 * stored as it is. A .gltf that points at .bin or texture files is converted to GLB instead.
 */
export function isSelfContainedGltf(json: unknown): boolean {
    if (!json || typeof json !== "object") return false;
    const j = json as { buffers?: { uri?: string }[]; images?: { uri?: string }[] };
    const inline = (uri?: string) => uri === undefined || uri.startsWith("data:");
    return (j.buffers ?? []).every((b) => inline(b.uri)) && (j.images ?? []).every((i) => inline(i.uri));
}

/** One model file to convert, with the files it may reference. */
export type ImportSource = {
    /** Import id; the host only reads files that belong to an import it started. */
    id: string;
    name: string;
    ext: string;
    /** URL the WebView can read the file from (file:// in Photoshop). */
    url: string;
    path: string;
    /** Material/texture/buffer files next to the model, relative to its folder ("textures/wood.png"). */
    resources: { name: string; url: string; path: string }[];
};

export type ImportBatch = {
    /** Models stored directly (GLB / self-contained glTF). */
    imported: LibraryItem[];
    /** Models the panel converts to GLB and hands back with library.addConverted. */
    toConvert: ImportSource[];
    /** Files that could not be read, with the reason. */
    failed: { name: string; error: string }[];
};
