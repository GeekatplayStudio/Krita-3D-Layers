/**
 * Offscreen still renders of a model for library thumbnails.
 *
 * Port of ImageExpress src/lib/modelThumbnail.ts (same three-point lighting and
 * ¾ camera), with two changes for the plugin: the result is a transparent PNG that the
 * host saves next to the model (so it is rendered once, not on every panel load), and
 * an environment map gives PBR materials their reflections. One shared renderer, one
 * render at a time.
 */
import * as THREE from "three";
import { EXRLoader } from "three-stdlib";
import { createGltfLoader } from "./loaders";
import { loadEnvironment } from "./environments";

let renderer: THREE.WebGLRenderer | null = null;
let envTexture: THREE.Texture | null = null;
let queue: Promise<unknown> = Promise.resolve();

function getRenderer(size: number) {
    if (!renderer) {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.setClearColor(0x000000, 0);
    }
    renderer.setPixelRatio(1);
    renderer.setSize(size, size, false);
    return renderer;
}

async function getEnvironment(r: THREE.WebGLRenderer): Promise<THREE.Texture | null> {
    if (envTexture) return envTexture;
    try {
        const url = await loadEnvironment("studio");
        const hdr = await new EXRLoader().loadAsync(url);
        const pmrem = new THREE.PMREMGenerator(r);
        envTexture = pmrem.fromEquirectangular(hdr).texture;
        hdr.dispose();
        pmrem.dispose();
    } catch {
        envTexture = null;
    }
    return envTexture;
}

function dispose(object: THREE.Object3D) {
    object.traverse((child) => {
        const mesh = child as THREE.Mesh;
        mesh.geometry?.dispose?.();
        const mats = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
        for (const m of mats) {
            for (const value of Object.values(m)) if (value instanceof THREE.Texture) value.dispose();
            m.dispose();
        }
    });
}

/** Renders `url` (glb/gltf) to a square transparent PNG data URL. */
export function renderModelThumbnail(url: string, size = 512): Promise<string> {
    const task = queue.then(async () => {
        const r = getRenderer(size);
        const gltf = await createGltfLoader(r).loadAsync(url);
        const model = gltf.scene;
        const scene = new THREE.Scene();
        scene.environment = await getEnvironment(r);
        // Reflections only: ImageExpress' three lights already expose the model fully.
        scene.environmentIntensity = 0.35;
        scene.add(new THREE.AmbientLight(0xffffff, 0.9));
        const key = new THREE.DirectionalLight(0xffffff, 1.8);
        key.position.set(5, 8, 6);
        scene.add(key);
        const fill = new THREE.DirectionalLight(0xffffff, 0.6);
        fill.position.set(-4, 2, -5);
        scene.add(fill);
        scene.add(model);

        const box = new THREE.Box3().setFromObject(model);
        const center = box.getCenter(new THREE.Vector3());
        const sphere = box.getBoundingSphere(new THREE.Sphere());
        model.position.sub(center);

        const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 1000);
        const radius = sphere.radius > 0 ? sphere.radius : 1;
        const distance = (radius / Math.sin(THREE.MathUtils.degToRad(20))) * 1.1;
        camera.position.set(0.6, 0.45, 0.75).normalize().multiplyScalar(distance);
        camera.near = distance / 100;
        camera.far = distance * 100;
        camera.updateProjectionMatrix();
        camera.lookAt(0, 0, 0);

        r.render(scene, camera);
        const dataUrl = r.domElement.toDataURL("image/png");
        dispose(model);
        return dataUrl;
    });
    queue = task.catch(() => undefined);
    return task;
}
