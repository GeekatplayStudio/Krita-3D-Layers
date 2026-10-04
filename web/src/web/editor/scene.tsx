/**
 * Scene parts of the 3D layer editor, ported from ImageExpress ThreeDLayerEditor.tsx.
 *
 * Differences from the original, all for predictable posing in Photoshop:
 * - the model is centred and normalised to a bounding radius of 1, so any service's
 *   units frame the same way and rotation turns around the model's own centre;
 * - EditorStage reproduces drei <Stage>'s lights (ambient + rembrandt key/fill) but
 *   without its <Center>/<Bounds>, which re-centred the model when it was rotated;
 * - the environment comes from bundled EXRs (see three/environments.ts).
 */
import React, { useEffect, useMemo, useRef } from "react";
import { useGLTF, Line, Environment } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { GIZMO_GROUP_NAME, GIZMO_ORBIT_RADIUS, vecScaleTo, type Vec3 } from "@shared/threeD";
import { extendGltfLoader } from "../three/loaders";

export type ModelInfo = { radius: number; meshes: number; triangles: number };

/** Loads the model, centres it and scales it to radius 1. Throws (Suspense/boundary) on failure. */
export function ModelViewer({ url, onInfo }: { url: string; onInfo?: (info: ModelInfo) => void }) {
    const { scene } = useGLTF(url, false, true, (loader) => extendGltfLoader(loader as never));
    const { object, info } = useMemo(() => {
        const clone = scene.clone(true);
        let meshes = 0;
        let triangles = 0;
        clone.traverse((child) => {
            const mesh = child as THREE.Mesh;
            if (mesh.isMesh) {
                mesh.castShadow = true;
                mesh.receiveShadow = true;
                meshes++;
                const g = mesh.geometry;
                triangles += g.index ? g.index.count / 3 : (g.attributes.position?.count ?? 0) / 3;
            }
        });
        const box = new THREE.Box3().setFromObject(clone);
        const center = box.getCenter(new THREE.Vector3());
        const radius = box.getBoundingSphere(new THREE.Sphere()).radius || 1;
        const wrapper = new THREE.Group();
        clone.position.sub(center);
        wrapper.add(clone);
        wrapper.scale.setScalar(1 / radius);
        return { object: wrapper, info: { radius, meshes, triangles: Math.round(triangles) } };
    }, [scene]);
    useEffect(() => {
        onInfo?.(info);
    }, [info, onInfo]);
    return <primitive object={object} />;
}

/**
 * A draggable "sun" on a fixed orbit sphere around the model (unchanged from ImageExpress).
 * Dragging changes the light DIRECTION; distance is a separate slider.
 */
export function LightGizmo({
    lightPosition,
    lightColor,
    visible,
    controlsRef,
    onDirectionChange,
}: {
    lightPosition: Vec3;
    lightColor: string;
    visible: boolean;
    controlsRef: React.RefObject<OrbitControlsImpl | null>;
    onDirectionChange: (direction: Vec3) => void;
}) {
    const draggingRef = useRef(false);
    const gizmoPos = useMemo(() => vecScaleTo(lightPosition, GIZMO_ORBIT_RADIUS), [lightPosition]);

    const projectRayToOrbit = (ray: THREE.Ray): Vec3 => {
        const o = ray.origin;
        const d = ray.direction;
        const b = 2 * o.dot(d);
        const c = o.lengthSq() - GIZMO_ORBIT_RADIUS * GIZMO_ORBIT_RADIUS;
        const disc = b * b - 4 * c;
        let point: THREE.Vector3;
        if (disc >= 0) {
            const t = (-b - Math.sqrt(disc)) / 2;
            point = o.clone().addScaledVector(d, t >= 0 ? t : (-b + Math.sqrt(disc)) / 2);
        } else {
            point = o.clone().addScaledVector(d, -b / 2).normalize().multiplyScalar(GIZMO_ORBIT_RADIUS);
        }
        return { x: point.x, y: point.y, z: point.z };
    };

    const handlePointerDown = (e: ThreeEvent<PointerEvent>) => {
        e.stopPropagation();
        draggingRef.current = true;
        (e.target as Element).setPointerCapture(e.pointerId);
        if (controlsRef.current) controlsRef.current.enabled = false;
    };
    const handlePointerMove = (e: ThreeEvent<PointerEvent>) => {
        if (!draggingRef.current) return;
        e.stopPropagation();
        onDirectionChange(projectRayToOrbit(e.ray));
    };
    const endDrag = (e: ThreeEvent<PointerEvent>) => {
        if (!draggingRef.current) return;
        draggingRef.current = false;
        (e.target as Element).releasePointerCapture(e.pointerId);
        if (controlsRef.current) controlsRef.current.enabled = true;
    };

    return (
        <group name={GIZMO_GROUP_NAME} visible={visible}>
            <Line points={[[gizmoPos.x, gizmoPos.y, gizmoPos.z], [0, 0, 0]]} color={lightColor} lineWidth={1} dashed dashScale={8} transparent opacity={0.55} />
            <mesh
                position={[gizmoPos.x, gizmoPos.y, gizmoPos.z]}
                onPointerDown={handlePointerDown}
                onPointerMove={handlePointerMove}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
                onPointerOver={() => {
                    document.body.style.cursor = "grab";
                }}
                onPointerOut={() => {
                    document.body.style.cursor = "auto";
                }}
            >
                <sphereGeometry args={[0.16, 24, 24]} />
                <meshBasicMaterial color={lightColor} toneMapped={false} />
            </mesh>
            <mesh position={[gizmoPos.x, gizmoPos.y, gizmoPos.z]}>
                <sphereGeometry args={[0.26, 24, 24]} />
                <meshBasicMaterial color={lightColor} transparent opacity={0.25} toneMapped={false} />
            </mesh>
        </group>
    );
}

/** drei <Stage>'s "rembrandt" lighting + environment, without its centring/bounds logic. */
export function EditorStage({
    intensity,
    radius,
    environmentUrl,
    environmentBackground,
    children,
}: {
    intensity: number;
    radius: number;
    environmentUrl: string | null;
    environmentBackground: boolean;
    children: React.ReactNode;
}) {
    const main: [number, number, number] = [1 * radius, 2 * radius, 1 * radius];
    const fill: [number, number, number] = [-2 * radius, -0.5 * radius, -2 * radius];
    return (
        <>
            <ambientLight intensity={intensity / 3} />
            <spotLight penumbra={1} position={main} intensity={intensity * 2} />
            <pointLight position={fill} intensity={intensity} />
            {children}
            {environmentUrl && <Environment files={environmentUrl} background={environmentBackground} environmentIntensity={1} />}
        </>
    );
}

/** Ground height of the model group after rotation/scale (bottom of its world bounds). */
export function groundOf(group: THREE.Object3D | null): number {
    if (!group) return -1;
    group.updateWorldMatrix(true, true);
    const box = new THREE.Box3().setFromObject(group);
    return Number.isFinite(box.min.y) ? box.min.y : -1;
}
