/**
 * glTF loading shared by the editor, previews and thumbnails: local Draco and Basis
 * decoders (shipped in web/draco and web/basis) and meshopt support.
 */
import { DRACOLoader, GLTFLoader, KTX2Loader, MeshoptDecoder } from "three-stdlib";
import type { WebGLRenderer } from "three";

export const DRACO_PATH = "./draco/";
export const BASIS_PATH = "./basis/";

let draco: DRACOLoader | null = null;
const ktx2ByRenderer = new WeakMap<WebGLRenderer, KTX2Loader>();

/** Configures a GLTFLoader the way useGLTF's `extendLoader` expects. */
export function extendGltfLoader(loader: GLTFLoader, renderer?: WebGLRenderer) {
    if (!draco) {
        draco = new DRACOLoader();
        draco.setDecoderPath(DRACO_PATH);
    }
    loader.setDRACOLoader(draco);
    loader.setMeshoptDecoder(typeof MeshoptDecoder === "function" ? (MeshoptDecoder as unknown as () => unknown)() as never : (MeshoptDecoder as never));
    if (renderer) {
        let ktx2 = ktx2ByRenderer.get(renderer);
        if (!ktx2) {
            ktx2 = new KTX2Loader().setTranscoderPath(BASIS_PATH).detectSupport(renderer);
            ktx2ByRenderer.set(renderer, ktx2);
        }
        loader.setKTX2Loader(ktx2);
    }
}

export function createGltfLoader(renderer?: WebGLRenderer): GLTFLoader {
    const loader = new GLTFLoader();
    extendGltfLoader(loader, renderer);
    return loader;
}
