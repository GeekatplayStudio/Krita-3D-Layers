/**
 * Converts a 3D file to GLB in the WebView, so the library can store every model the same way.
 *
 * Each format is parsed with three.js' own loader. External files the model references
 * (the .mtl of an OBJ, textures of FBX/DAE/3DS/OBJ, buffers of a .gltf) are matched to the
 * files the host found next to the model by relative path or file name: artists' absolute
 * paths such as "C:\Users\someone\textures\wood.jpg" still find "wood.jpg". They are read as
 * blobs, so nothing is loaded from file:// by <img> (no tainted canvas, no CORS).
 *
 * Formats whose texture names are only known while parsing run twice. The first pass records
 * which files are asked for (images get a placeholder); the second pass gets the real files.
 * The result is cleaned up and exported with GLTFExporter:
 * - lights and cameras are removed;
 * - Phong/Lambert/Toon materials become MeshStandardMaterial;
 * - missing normals are computed;
 * - Z-up formats (STL, 3MF, AMF, VOX) are turned upright.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { FBXLoader } from "three/examples/jsm/loaders/FBXLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { MTLLoader } from "three/examples/jsm/loaders/MTLLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { ColladaLoader } from "three/examples/jsm/loaders/ColladaLoader.js";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";
import { AMFLoader } from "three/examples/jsm/loaders/AMFLoader.js";
import { TDSLoader } from "three/examples/jsm/loaders/TDSLoader.js";
import { VRMLLoader } from "three/examples/jsm/loaders/VRMLLoader.js";
import { USDLoader } from "three/examples/jsm/loaders/USDLoader.js";
import { VOXLoader, buildMesh } from "three/examples/jsm/loaders/VOXLoader.js";
import { TGALoader } from "three/examples/jsm/loaders/TGALoader.js";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
import { baseName, extOf, formatOf, type ImportSource } from "@shared/modelFormats";

export type ReadBytes = (url: string, path: string) => Promise<Uint8Array>;
export type ConvertResult = { glb: Uint8Array; meshes: number; triangles: number; notes: string[] };

/** 1×1 transparent PNG, standing in for textures during the first pass. */
const PLACEHOLDER_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";
const IMAGE_EXT = /\.(png|jpe?g|tga|bmp|gif|webp|tiff?)$/i;
const MIME: Record<string, string> = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif", webp: "image/webp", bmp: "image/bmp", tif: "image/tiff", tiff: "image/tiff" };
const MAX_TEXTURE = 4096;
const SETTLE_TIMEOUT_MS = 120_000;

type Resource = ImportSource["resources"][number];

/** Finds the file a model refers to: by relative path first, then by file name. */
export function resolveResource(requested: string, resources: readonly Resource[]): Resource | undefined {
    let url = requested.split(/[?#]/)[0];
    try {
        url = decodeURIComponent(url);
    } catch {
        // keep as is
    }
    const norm = url.replace(/\\/g, "/").replace(/^file:\/+/i, "").toLowerCase();
    let best: Resource | undefined;
    for (const r of resources) {
        const rel = r.name.toLowerCase();
        if ((norm === rel || norm.endsWith(`/${rel}`)) && (!best || rel.length > best.name.length)) best = r;
    }
    if (best) return best;
    const name = baseName(norm);
    return resources.find((r) => baseName(r.name).toLowerCase() === name);
}

export async function convertToGlb(source: ImportSource, read: ReadBytes, onProgress?: (message: string) => void): Promise<ConvertResult> {
    const notes: string[] = [];
    const ext = source.ext;
    const blobs = new Map<string, string>(); // resource path → blob URL
    const jpegBlobs = new Set<string>();
    const loadResource = async (r: Resource) => {
        if (blobs.has(r.path)) return;
        const bytes = await read(r.url, r.path);
        const type = MIME[extOf(r.name)] ?? "application/octet-stream";
        const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type }));
        blobs.set(r.path, url);
        if (type === "image/jpeg") jpegBlobs.add(url);
    };

    try {
        onProgress?.(`Reading ${source.name}.${ext}`);
        const main = await read(source.url, source.path);

        // References known before parsing: a .gltf's buffers and images, an .obj's material libraries.
        if (ext === "gltf") {
            const json = JSON.parse(new TextDecoder().decode(main)) as { buffers?: { uri?: string }[]; images?: { uri?: string }[] };
            for (const uri of [...(json.buffers ?? []), ...(json.images ?? [])].map((x) => x.uri).filter((u): u is string => !!u && !u.startsWith("data:"))) {
                const r = resolveResource(uri, source.resources);
                if (r) await loadResource(r);
                else notes.push(`Missing file: ${uri}`);
            }
        }
        let mtlTexts: string[] = [];
        if (ext === "obj") {
            const names = [...new TextDecoder().decode(main).matchAll(/^\s*mtllib\s+(.+?)\s*$/gm)].map((m) => m[1]);
            for (const n of names) {
                const r = resolveResource(n, source.resources);
                if (!r) {
                    notes.push(`Missing material library: ${n}`);
                    continue;
                }
                mtlTexts.push(new TextDecoder().decode(await read(r.url, r.path)));
            }
        }

        const parse = (pass: { record?: Set<Resource>; missing?: Set<string> }) => parseModel(ext, main, mtlTexts, source.resources, blobs, pass);

        onProgress?.(`Converting ${source.name}.${ext}`);
        const wanted = new Set<Resource>();
        const missing = new Set<string>();
        let root = await parse({ record: wanted, missing });
        const toFetch = [...wanted].filter((r) => !blobs.has(r.path));
        if (toFetch.length) {
            onProgress?.(`Loading ${toFetch.length} texture${toFetch.length === 1 ? "" : "s"} for ${source.name}`);
            for (const r of toFetch) {
                try {
                    await loadResource(r);
                } catch (err) {
                    notes.push(`Could not read ${r.name}: ${(err as Error).message}`);
                }
            }
            root = await parse({});
        }
        for (const m of missing) notes.push(`Missing texture: ${baseName(m)}`);
        mtlTexts = [];

        const { meshes, triangles } = prepare(root, ext, jpegBlobs);
        if (!meshes) throw new Error("No geometry found in this file.");
        if (formatOf(`x.${ext}`)?.zUp) {
            const upright = new THREE.Group();
            upright.rotation.x = -Math.PI / 2;
            upright.add(root);
            root = new THREE.Group().add(upright);
        }

        onProgress?.(`Packing ${source.name} as GLB`);
        const exporter = new GLTFExporter();
        const glb = (await exporter.parseAsync(root, { binary: true, onlyVisible: true, maxTextureSize: MAX_TEXTURE })) as ArrayBuffer;
        return { glb: new Uint8Array(glb), meshes, triangles, notes };
    } finally {
        for (const url of blobs.values()) URL.revokeObjectURL(url);
    }
}

/** A LoadingManager that maps references to blobs and can wait until every texture finished loading. */
function makeManager(resources: readonly Resource[], blobs: Map<string, string>, pass: { record?: Set<Resource>; missing?: Set<string> }) {
    const manager = new THREE.LoadingManager();
    let pending = 0;
    const start = manager.itemStart.bind(manager);
    const end = manager.itemEnd.bind(manager);
    manager.itemStart = (url: string) => {
        pending++;
        start(url);
    };
    manager.itemEnd = (url: string) => {
        pending = Math.max(0, pending - 1);
        end(url);
    };
    manager.setURLModifier((url) => {
        if (/^(data|blob):/i.test(url)) return url;
        const r = resolveResource(url, resources);
        const blob = r && blobs.get(r.path);
        if (blob) return blob;
        if (r) pass.record?.add(r);
        else pass.missing?.add(url);
        return IMAGE_EXT.test(url.split(/[?#]/)[0]) ? PLACEHOLDER_PNG : url;
    });
    manager.addHandler(/\.tga$/i, new TGALoader(manager));
    const settle = async () => {
        const started = Date.now();
        let quiet = 0;
        while (Date.now() - started < SETTLE_TIMEOUT_MS) {
            await new Promise((r) => setTimeout(r, 40));
            quiet = pending === 0 ? quiet + 1 : 0;
            if (quiet >= 3) return;
        }
    };
    return { manager, settle };
}

const buffer = (bytes: Uint8Array): ArrayBuffer => (bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength ? (bytes.buffer as ArrayBuffer) : (bytes.slice().buffer as ArrayBuffer));
const text = (bytes: Uint8Array) => new TextDecoder().decode(bytes);

async function parseModel(
    ext: string,
    main: Uint8Array,
    mtlTexts: string[],
    resources: readonly Resource[],
    blobs: Map<string, string>,
    pass: { record?: Set<Resource>; missing?: Set<string> },
): Promise<THREE.Object3D> {
    const { manager, settle } = makeManager(resources, blobs, pass);
    let root: THREE.Object3D;
    switch (ext) {
        case "glb":
        case "gltf":
            root = (await new GLTFLoader(manager).parseAsync(buffer(main), "")).scene;
            break;
        case "fbx":
            root = new FBXLoader(manager).parse(buffer(main), "");
            break;
        case "obj": {
            const loader = new OBJLoader(manager);
            if (mtlTexts.length) {
                const mtl = new MTLLoader(manager);
                const materials = mtl.parse(mtlTexts.join("\n"), "");
                materials.preload();
                loader.setMaterials(materials);
            }
            root = loader.parse(text(main));
            break;
        }
        case "stl": {
            const geometry = new STLLoader(manager).parse(buffer(main));
            const colored = (geometry as THREE.BufferGeometry & { hasColors?: boolean }).hasColors === true;
            root = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: colored ? 0xffffff : 0xb8b8b8, vertexColors: colored, roughness: 0.6 }));
            break;
        }
        case "ply": {
            const geometry = new PLYLoader(manager).parse(buffer(main));
            const colored = geometry.hasAttribute("color");
            if (geometry.index || geometry.getAttribute("position").count % 3 === 0) {
                if (!geometry.hasAttribute("normal")) geometry.computeVertexNormals();
                root = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: colored ? 0xffffff : 0xb8b8b8, vertexColors: colored, roughness: 0.7 }));
            } else {
                root = new THREE.Points(geometry, new THREE.PointsMaterial({ size: 0.01, vertexColors: colored }));
            }
            break;
        }
        case "dae": {
            const collada = new ColladaLoader(manager).parse(text(main), "");
            if (!collada) throw new Error("This Collada file could not be read.");
            root = collada.scene;
            break;
        }
        case "3mf":
            root = new ThreeMFLoader(manager).parse(buffer(main));
            break;
        case "amf":
            root = new AMFLoader(manager).parse(buffer(main));
            break;
        case "3ds":
            root = new TDSLoader(manager).parse(buffer(main), "");
            break;
        case "wrl":
            root = new VRMLLoader(manager).parse(text(main), "");
            break;
        case "usd":
        case "usda":
        case "usdc":
        case "usdz": {
            const loader = new USDLoader(manager);
            root = await new Promise<THREE.Object3D>((resolve, reject) => {
                const group = loader.parse(buffer(main), "", resolve, reject);
                // Older parses return the group without calling back; settle() covers the textures.
                if (group) setTimeout(() => resolve(group), 0);
            });
            break;
        }
        case "vox": {
            const result = new VOXLoader(manager).parse(buffer(main)) as unknown as { chunks?: unknown[]; scene?: THREE.Object3D } | unknown[] | undefined;
            if (!result) throw new Error("This MagicaVoxel file could not be read.");
            const chunks = Array.isArray(result) ? result : (result.chunks ?? []);
            const group = new THREE.Group();
            for (const chunk of chunks) group.add(buildMesh(chunk as Parameters<typeof buildMesh>[0]));
            root = !Array.isArray(result) && result.scene ? result.scene : group;
            break;
        }
        default:
            throw new Error(`.${ext} files cannot be converted.`);
    }
    await settle();
    return root;
}

/** Removes lights and cameras, converts materials for glTF, fills in normals; counts geometry. */
function prepare(root: THREE.Object3D, ext: string, jpegBlobs: Set<string>): { meshes: number; triangles: number } {
    const remove: THREE.Object3D[] = [];
    let meshes = 0;
    let triangles = 0;
    root.traverse((o) => {
        if ((o as THREE.Light).isLight || (o as THREE.Camera).isCamera) {
            remove.push(o);
            return;
        }
        const mesh = o as THREE.Mesh;
        if (mesh.isMesh || (o as THREE.Points).isPoints) {
            meshes++;
            const g = mesh.geometry as THREE.BufferGeometry;
            const pos = g.getAttribute("position");
            if (!pos) return;
            if (mesh.isMesh) {
                triangles += g.index ? g.index.count / 3 : pos.count / 3;
                if (!g.hasAttribute("normal")) g.computeVertexNormals();
                mesh.material = Array.isArray(mesh.material) ? mesh.material.map((m) => toStandard(m, ext)) : toStandard(mesh.material, ext);
            }
            for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
                for (const value of Object.values(m)) {
                    const tex = value as THREE.Texture;
                    const src = (tex?.isTexture && (tex.image as HTMLImageElement | undefined)?.src) || "";
                    // Keep JPEG textures as JPEG in the GLB (PNG would be several times larger).
                    if (src && jpegBlobs.has(src)) tex.userData.mimeType = "image/jpeg";
                }
            }
        }
    });
    for (const o of remove) o.parent?.remove(o);
    return { meshes, triangles: Math.round(triangles) };
}

/** glTF has metallic-roughness materials (and unlit); classic Phong/Lambert materials are mapped to them. */
function toStandard(material: THREE.Material, ext: string): THREE.Material {
    const flags = material as unknown as { isMeshStandardMaterial?: boolean; isMeshBasicMaterial?: boolean };
    if (flags.isMeshStandardMaterial || flags.isMeshBasicMaterial) return material;
    const src = material as unknown as THREE.MeshPhongMaterial;
    const shininess = typeof src.shininess === "number" ? src.shininess : 30;
    const out = new THREE.MeshStandardMaterial({
        name: material.name,
        color: src.color ? src.color.clone() : new THREE.Color(0xcccccc),
        map: src.map ?? null,
        normalMap: src.normalMap ?? null,
        bumpMap: src.bumpMap ?? null,
        aoMap: src.aoMap ?? null,
        alphaMap: src.alphaMap ?? null,
        emissive: src.emissive ? src.emissive.clone() : new THREE.Color(0),
        emissiveMap: src.emissiveMap ?? null,
        emissiveIntensity: src.emissiveIntensity ?? 1,
        opacity: material.opacity,
        transparent: material.transparent,
        alphaTest: material.alphaTest,
        side: material.side,
        vertexColors: material.vertexColors,
        // Shininess 0–100+ → roughness 1–0.2; specular colour is not carried over.
        roughness: Math.min(1, Math.max(0.2, 1 - Math.sqrt(Math.min(shininess, 100) / 100) * 0.8)),
        metalness: 0,
    });
    if (src.normalScale) out.normalScale.copy(src.normalScale);
    if (ext === "fbx" && out.map) out.color.set(0xffffff);
    return out;
}
