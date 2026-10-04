/**
 * High-resolution capture of the editor view (ImageExpress handleCapture, extended).
 *
 * The live canvas is temporarily resized to the export resolution at pixel ratio 1,
 * rendered once with the light gizmo hidden, copied to a 2D canvas, and restored.
 * The 2D copy gives the PNG (with transparency) and the bounding box of the visible
 * object, which the host uses to fit a new layer over the source area.
 */
import * as THREE from "three";
import { alphaBounds, type Box } from "@shared/placement";
import { GIZMO_GROUP_NAME } from "@shared/threeD";

export type Capture = { pngBase64: string; width: number; height: number; contentBounds?: Box };

function blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).replace(/^data:[^,]*,/, ""));
        reader.onerror = () => reject(reader.error ?? new Error("Could not read the render"));
        reader.readAsDataURL(blob);
    });
}

export async function captureView(gl: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera, width: number, height: number): Promise<Capture> {
    const prevSize = gl.getSize(new THREE.Vector2());
    const prevRatio = gl.getPixelRatio();
    const prevAspect = camera.aspect;
    const gizmo = scene.getObjectByName(GIZMO_GROUP_NAME);
    const gizmoVisible = gizmo?.visible ?? false;
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    try {
        if (gizmo) gizmo.visible = false;
        gl.setPixelRatio(1);
        gl.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        gl.render(scene, camera);
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        if (!ctx) throw new Error("No 2D canvas context");
        ctx.drawImage(gl.domElement, 0, 0, width, height);
    } finally {
        if (gizmo) gizmo.visible = gizmoVisible;
        gl.setPixelRatio(prevRatio);
        gl.setSize(prevSize.x, prevSize.y, false);
        camera.aspect = prevAspect;
        camera.updateProjectionMatrix();
        gl.render(scene, camera);
    }
    const ctx = canvas.getContext("2d")!;
    const contentBounds = alphaBounds(ctx.getImageData(0, 0, width, height).data, width, height);
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("PNG encoding failed"))), "image/png"));
    return { pngBase64: await blobToBase64(blob), width, height, contentBounds };
}
