/**
 * The 3D pose & light editor — a full-window port of ImageExpress's ThreeDLayerEditor.
 *
 * Kept from ImageExpress: draggable sun widget, light presets, light intensity /
 * distance / colour / ambient, environment + intensity, cast and contact shadows,
 * model rotate/scale, camera views, export resolution, remembered lighting defaults.
 * Added for Photoshop: rotation on all three axes, field of view, environment as a
 * visible background, "match document" resolution, and a viewport that always has the
 * export aspect ratio, so what you frame is exactly what lands in the layer.
 * "Show document" puts the document's layers below the 3D layer behind the model and the
 * layers above it in front, mapped to where the render goes (shared/documentView.ts).
 */
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { ContactShadows, OrbitControls as DreiOrbitControls, useProgress } from "@react-three/drei";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { Box, Camera, Check, Image as ImageIcon, Layers, Monitor, RotateCcw, Sun, Wand2, X, Palette } from "lucide-react";
import type { DocumentView, EditorInit, EditorResult } from "@shared/protocol";
import type { EditorViewPrefs } from "@shared/settings";
import { base64ToBytes } from "@shared/bytes";
import { documentRect, placementScale, viewRegion } from "@shared/documentView";
import {
    CAMERA_VIEWS,
    DEFAULT_CAMERA_FOV,
    DEFAULT_CAMERA_POSITION,
    ENVIRONMENTS,
    LIGHT_PRESETS,
    RESOLUTION_PRESETS,
    clampResolution,
    lightingOf,
    vecLength,
    vecScaleTo,
    type LightPreset,
    type LightingDefaults,
    type ThreeDSettings,
    type Vec3,
} from "@shared/threeD";
import { ChipButton, ColorField, MiniSlider, MiniToggle, SectionTitle } from "./controls";
import { Dropdown } from "../components/Dropdown";
import { EditorStage, LightGizmo, ModelViewer, groundOf, type ModelInfo } from "./scene";
import { captureView } from "./capture";
import { ModelErrorBoundary } from "../components/ErrorBoundary";
import { useEnvironmentUrl } from "../three/environments";

type Props = {
    init: EditorInit;
    modelUrl: string;
    onComplete: (result: EditorResult) => Promise<void> | void;
    onCancel: () => void;
    onRememberLighting?: (lighting: LightingDefaults) => void;
    /** Reads the document around the 3D layer (null when there is none). */
    loadDocumentView?: () => Promise<DocumentView | null>;
    onRememberView?: (view: EditorViewPrefs) => void;
};

const DEFAULT_VIEW: EditorViewPrefs = { showDocument: true, showAbove: true, aboveOpacity: 1 };

/** Object URL of a base64 PNG (much lighter on the page than a multi-MB data: URL). */
function pngUrl(base64: string): string {
    return URL.createObjectURL(new Blob([base64ToBytes(base64) as BlobPart], { type: "image/png" }));
}

type CaptureGL = { gl: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera };

function LoadingOverlay() {
    const { active, progress } = useProgress();
    if (!active) return null;
    return (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 pointer-events-none">
            <div className="w-48 h-1.5 rounded bg-secondary overflow-hidden">
                <div className="h-full bg-primary transition-all" style={{ width: `${Math.round(progress)}%` }} />
            </div>
            <div className="text-[11px] text-muted-foreground">Loading model… {Math.round(progress)}%</div>
        </div>
    );
}

/** Largest box with `aspect` that fits in `w`×`h`. */
function fitAspect(w: number, h: number, aspect: number) {
    if (w <= 0 || h <= 0) return { width: 0, height: 0 };
    return w / h > aspect ? { width: Math.floor(h * aspect), height: h } : { width: w, height: Math.floor(w / aspect) };
}

export default function ThreeDLayerEditor({ init, modelUrl, onComplete, onCancel, onRememberLighting, loadDocumentView, onRememberView }: Props) {
    const s = init.settings;
    const [resolution, setResolution] = useState(clampResolution(s.resolution));
    const [lightPosition, setLightPosition] = useState<Vec3>(s.lightPosition);
    const [lightIntensity, setLightIntensity] = useState(s.lightIntensity);
    const [lightColor, setLightColor] = useState(s.lightColor);
    const [ambientIntensity, setAmbientIntensity] = useState(s.ambientIntensity ?? 0.35);
    const [environment, setEnvironment] = useState(s.environment ?? "city");
    const [envIntensity, setEnvIntensity] = useState(s.envIntensity ?? 0.6);
    const [environmentBackground, setEnvironmentBackground] = useState(!!s.environmentBackground);
    const [castShadowEnabled, setCastShadowEnabled] = useState(s.castShadowEnabled);
    const [castShadowBlur, setCastShadowBlur] = useState(s.castShadowBlur);
    const [castShadowIntensity, setCastShadowIntensity] = useState(s.castShadowIntensity);
    const [contactShadowEnabled, setContactShadowEnabled] = useState(s.contactShadowEnabled);
    const [contactShadowBlur, setContactShadowBlur] = useState(s.contactShadowBlur);
    const [contactShadowIntensity, setContactShadowIntensity] = useState(s.contactShadowIntensity);
    const [rotX, setRotX] = useState(s.modelRotationX ?? 0);
    const [rotY, setRotY] = useState(s.modelRotationY ?? 0);
    const [rotZ, setRotZ] = useState(s.modelRotationZ ?? 0);
    const [modelScale, setModelScale] = useState(s.modelScale ?? 1);
    const [fov, setFov] = useState(s.cameraFov ?? DEFAULT_CAMERA_FOV);
    const [gizmoVisible, setGizmoVisible] = useState(true);
    const [activePreset, setActivePreset] = useState<string | null>(null);
    const [groundY, setGroundY] = useState(-1);
    const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null);
    const [loadFailed, setLoadFailed] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [gl, setGl] = useState<CaptureGL | null>(null);
    const [area, setArea] = useState({ width: 0, height: 0 });
    const [view, setView] = useState<EditorViewPrefs>(init.view ?? DEFAULT_VIEW);
    const [docView, setDocView] = useState<DocumentView | null>(null);
    const [docState, setDocState] = useState<"idle" | "loading" | "ready" | "none" | "error">("idle");
    const [docError, setDocError] = useState<string | null>(null);

    const controlsRef = useRef<OrbitControlsImpl | null>(null);
    const modelGroupRef = useRef<THREE.Group>(null);
    const viewportRef = useRef<HTMLDivElement>(null);
    const cameraInitialized = useRef(false);
    const envUrl = useEnvironmentUrl(environment);

    // Fit the canvas to the export aspect ratio inside the available space.
    useEffect(() => {
        const el = viewportRef.current;
        if (!el) return;
        const update = () => setArea({ width: el.clientWidth - 24, height: el.clientHeight - 24 });
        update();
        const ro = new ResizeObserver(update);
        ro.observe(el);
        return () => ro.disconnect();
    }, []);
    const frame = fitAspect(area.width, area.height, resolution.width / resolution.height);

    // "Show document": read the document once, the first time it is shown.
    const loadDocument = useCallback(() => {
        if (!loadDocumentView) return setDocState("none");
        setDocState("loading");
        setDocError(null);
        loadDocumentView().then(
            (v) => {
                setDocView(v);
                setDocState(v ? "ready" : "none");
            },
            (err: Error) => {
                setDocError(err.message);
                setDocState("error");
            },
        );
    }, [loadDocumentView]);
    useEffect(() => {
        if (view.showDocument && docState === "idle") loadDocument();
    }, [view.showDocument, docState, loadDocument]);
    const docUrls = useMemo(() => ({ below: docView?.below ? pngUrl(docView.below.pngBase64) : null, above: docView?.above ? pngUrl(docView.above.pngBase64) : null }), [docView]);
    useEffect(
        () => () => {
            if (docUrls.below) URL.revokeObjectURL(docUrls.below);
            if (docUrls.above) URL.revokeObjectURL(docUrls.above);
        },
        [docUrls],
    );
    // Remember the view options for next time (not on the first render: nothing changed yet).
    const viewChanged = useRef(false);
    useEffect(() => {
        if (!viewChanged.current) {
            viewChanged.current = true;
            return;
        }
        if (!onRememberView) return;
        const t = window.setTimeout(() => onRememberView(view), 400);
        return () => window.clearTimeout(t);
    }, [view, onRememberView]);
    const showingDoc = view.showDocument && docState === "ready" && docView ? docView : null;
    // The part of the document the render covers, and where the canvas sits in the viewport.
    const region = showingDoc ? viewRegion(showingDoc, resolution, showingDoc.frame) : null;
    const docRect = showingDoc && region ? documentRect(showingDoc, region, frame) : null;
    const enlarged = region ? placementScale(region, resolution) : 1;

    // Restore the saved camera once the controls exist.
    useEffect(() => {
        if (cameraInitialized.current || !gl || !controlsRef.current) return;
        const p = s.cameraPosition ?? DEFAULT_CAMERA_POSITION;
        const t = s.cameraTarget ?? { x: 0, y: 0, z: 0 };
        gl.camera.position.set(p.x, p.y, p.z);
        controlsRef.current.target.set(t.x, t.y, t.z);
        controlsRef.current.update();
        cameraInitialized.current = true;
    }, [gl, s.cameraPosition, s.cameraTarget]);

    useEffect(() => {
        if (!gl) return;
        gl.camera.fov = fov;
        gl.camera.updateProjectionMatrix();
    }, [gl, fov]);

    // Model transform: mutate the group directly (no re-mount, no env reload).
    useEffect(() => {
        const g = modelGroupRef.current;
        if (!g) return;
        g.rotation.set(THREE.MathUtils.degToRad(rotX), THREE.MathUtils.degToRad(rotY), THREE.MathUtils.degToRad(rotZ));
        g.scale.setScalar(modelScale);
        setGroundY(groundOf(g));
    }, [rotX, rotY, rotZ, modelScale, modelInfo]);

    // Remember lighting for the next NEW model (ImageExpress behaviour); reopened layers never overwrite it.
    const lighting = useMemo(
        () =>
            lightingOf({
                lightPosition,
                lightIntensity,
                lightColor,
                ambientIntensity,
                environment,
                envIntensity,
                castShadowEnabled,
                castShadowBlur,
                castShadowIntensity,
                contactShadowEnabled,
                contactShadowBlur,
                contactShadowIntensity,
                resolution,
            }),
        [lightPosition, lightIntensity, lightColor, ambientIntensity, environment, envIntensity, castShadowEnabled, castShadowBlur, castShadowIntensity, contactShadowEnabled, contactShadowBlur, contactShadowIntensity, resolution],
    );
    useEffect(() => {
        if (init.mode !== "new" || !init.rememberLighting || !onRememberLighting) return;
        const t = window.setTimeout(() => onRememberLighting(lighting), 600);
        return () => window.clearTimeout(t);
    }, [lighting, init.mode, init.rememberLighting, onRememberLighting]);

    const lightDistance = vecLength(lightPosition);
    const lightDistanceRef = useRef(lightDistance);
    lightDistanceRef.current = lightDistance;

    const handleGizmoDirection = useCallback((direction: Vec3) => {
        setActivePreset(null);
        setLightPosition(vecScaleTo(direction, lightDistanceRef.current));
    }, []);

    const applyPreset = (preset: LightPreset) => {
        setActivePreset(preset.name);
        setLightPosition(vecScaleTo(preset.direction, lightDistance));
        setLightIntensity(preset.intensity);
        setLightColor(preset.color);
        setAmbientIntensity(preset.ambient);
    };

    const applyCameraView = (direction: Vec3) => {
        if (!gl || !controlsRef.current) return;
        const target = controlsRef.current.target;
        const dist = gl.camera.position.distanceTo(target);
        const dir = vecScaleTo(direction, dist);
        gl.camera.position.set(target.x + dir.x, target.y + dir.y, target.z + dir.z);
        controlsRef.current.update();
    };

    const resetCamera = () => {
        if (!gl || !controlsRef.current) return;
        gl.camera.position.set(DEFAULT_CAMERA_POSITION.x, DEFAULT_CAMERA_POSITION.y, DEFAULT_CAMERA_POSITION.z);
        controlsRef.current.target.set(0, 0, 0);
        controlsRef.current.update();
        setFov(DEFAULT_CAMERA_FOV);
    };

    const resetPose = () => {
        setRotX(0);
        setRotY(0);
        setRotZ(0);
        setModelScale(1);
    };

    const buildSettings = (): ThreeDSettings => {
        const c = controlsRef.current;
        return {
            ...lighting,
            resolution,
            environmentBackground,
            modelRotationX: rotX,
            modelRotationY: rotY,
            modelRotationZ: rotZ,
            modelScale,
            cameraFov: fov,
            cameraPosition: c ? { x: c.object.position.x, y: c.object.position.y, z: c.object.position.z } : s.cameraPosition,
            cameraTarget: c ? { x: c.target.x, y: c.target.y, z: c.target.z } : s.cameraTarget,
        };
    };

    const handleOk = async () => {
        if (!gl || busy || loadFailed) return;
        setBusy(true);
        setError(null);
        try {
            const capture = await captureView(gl.gl, gl.scene, gl.camera, resolution.width, resolution.height);
            await onComplete({ ...capture, settings: buildSettings(), frame: region ?? undefined });
        } catch (err) {
            setError((err as Error).message);
            setBusy(false);
        }
    };

    // Esc = cancel, Ctrl/Cmd+Enter = OK.
    const okRef = useRef(handleOk);
    okRef.current = handleOk;
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") onCancel();
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void okRef.current();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onCancel]);

    const effectiveRadius = Math.max(0.5, modelScale);
    const shadowExtent = Math.max(3, effectiveRadius * 3);
    const floorSize = Math.max(12, effectiveRadius * 12);
    const doc = init.document;

    return (
        <div className="flex flex-col h-full bg-card text-foreground">
            <div className="flex-1 flex min-h-0">
                <div ref={viewportRef} className="flex-1 relative min-h-0 overflow-hidden flex items-center justify-center bg-background" onPointerDown={(e) => e.stopPropagation()}>
                    <div className="relative checkerboard shadow-lg overflow-hidden" style={{ width: frame.width, height: frame.height }} data-testid="viewport">
                        {docRect && docUrls.below && <img src={docUrls.below} alt="" draggable={false} data-testid="doc-below" className="absolute max-w-none pointer-events-none select-none" style={docRect} />}
                        <ModelErrorBoundary
                            onError={(e) => setLoadFailed(e.message)}
                            fallback={
                                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center px-6">
                                    <p className="text-sm font-medium">This model could not be loaded</p>
                                    <p className="text-[11px] text-muted-foreground max-w-xs">{loadFailed ?? "The file may be missing or in a format the viewer cannot read."}</p>
                                    <button type="button" onClick={onCancel} className="mt-1 h-7 px-3 rounded-md border border-border text-[11px] hover:bg-secondary">
                                        Close
                                    </button>
                                </div>
                            }
                        >
                            <Canvas
                                shadows
                                gl={{ preserveDrawingBuffer: true, alpha: true, antialias: true }}
                                camera={{ position: [DEFAULT_CAMERA_POSITION.x, DEFAULT_CAMERA_POSITION.y, DEFAULT_CAMERA_POSITION.z], fov }}
                                onCreated={({ gl: renderer, scene, camera }) => {
                                    renderer.shadowMap.enabled = true;
                                    // VSM: real blurred shadow edges at full map resolution (see ImageExpress notes).
                                    renderer.shadowMap.type = THREE.VSMShadowMap;
                                    setGl({ gl: renderer, scene, camera: camera as THREE.PerspectiveCamera });
                                }}
                            >
                                <ambientLight intensity={ambientIntensity} />
                                <directionalLight
                                    key={`shadow-${castShadowBlur}-${castShadowEnabled}`}
                                    position={[lightPosition.x, lightPosition.y, lightPosition.z]}
                                    intensity={lightIntensity}
                                    color={lightColor}
                                    castShadow={castShadowEnabled}
                                    shadow-mapSize-width={2048}
                                    shadow-mapSize-height={2048}
                                    shadow-radius={Math.max(1, castShadowBlur * 0.6)}
                                    shadow-blurSamples={Math.min(32, Math.max(8, Math.round(castShadowBlur / 2) + 8))}
                                    shadow-bias={-0.0001}
                                    shadow-normalBias={0.02}
                                    shadow-camera-near={0.1}
                                    shadow-camera-far={Math.max(50, lightDistance + effectiveRadius * 6)}
                                    shadow-camera-left={-shadowExtent}
                                    shadow-camera-right={shadowExtent}
                                    shadow-camera-top={shadowExtent}
                                    shadow-camera-bottom={-shadowExtent}
                                />
                                {castShadowEnabled && (
                                    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, groundY, 0]} receiveShadow>
                                        <planeGeometry args={[floorSize, floorSize]} />
                                        <shadowMaterial opacity={castShadowIntensity} transparent />
                                    </mesh>
                                )}
                                {contactShadowEnabled && (
                                    <ContactShadows position={[0, groundY + 0.02, 0]} scale={Math.max(3.5, effectiveRadius * 5)} blur={contactShadowBlur} opacity={contactShadowIntensity} far={Math.max(1.2, effectiveRadius * 1.5)} color="#000000" />
                                )}
                                <EditorStage intensity={envIntensity} radius={effectiveRadius} environmentUrl={envUrl} environmentBackground={environmentBackground}>
                                    <group ref={modelGroupRef}>
                                        <Suspense fallback={null}>
                                            <ModelViewer url={modelUrl} onInfo={setModelInfo} />
                                        </Suspense>
                                    </group>
                                </EditorStage>
                                <LightGizmo lightPosition={lightPosition} lightColor={lightColor} visible={gizmoVisible} controlsRef={controlsRef} onDirectionChange={handleGizmoDirection} />
                                <DreiOrbitControls ref={controlsRef} makeDefault autoRotate={false} enableDamping={false} />
                            </Canvas>
                        </ModelErrorBoundary>
                        {docRect && view.showAbove && docUrls.above && (
                            <img src={docUrls.above} alt="" draggable={false} data-testid="doc-above" className="absolute max-w-none pointer-events-none select-none" style={{ ...docRect, opacity: view.aboveOpacity }} />
                        )}
                        {/* The canvas edge, for where the render reaches past the document. */}
                        {docRect && <div className="absolute pointer-events-none" style={{ ...docRect, boxShadow: "0 0 0 1px rgba(255,255,255,0.35)" }} />}
                        <LoadingOverlay />
                        {!loadFailed && (
                            <div className="absolute bottom-3 left-1/2 -translate-x-1/2 text-[11px] text-muted-foreground bg-background/80 px-3 py-1 rounded-full pointer-events-none whitespace-nowrap">
                                Drag the sun to light • Drag to orbit • Right-drag to pan • Scroll to zoom
                            </div>
                        )}
                    </div>
                </div>

                <aside className="w-64 border-l border-border bg-card overflow-y-auto p-3 text-xs shrink-0" data-testid="editor-sidebar">
                    <SectionTitle icon={<Layers size={12} />}>Document</SectionTitle>
                    <div className="space-y-2.5" data-testid="document-section">
                        <MiniToggle testId="show-document" label="Show document" checked={view.showDocument} onChange={(v) => setView((p) => ({ ...p, showDocument: v }))} />
                        {view.showDocument && docState === "loading" && <p className="text-[10px] text-muted-foreground">Reading the document…</p>}
                        {view.showDocument && docState === "none" && <p className="text-[10px] text-muted-foreground">No document to show.</p>}
                        {view.showDocument && docState === "error" && (
                            <p className="text-[10px] text-danger leading-snug">
                                Could not read the document: {docError}{" "}
                                <button type="button" className="underline" onClick={loadDocument}>
                                    Try again
                                </button>
                            </p>
                        )}
                        {showingDoc?.above && (
                            <>
                                <MiniToggle testId="show-above" label="Layers above" checked={view.showAbove} onChange={(v) => setView((p) => ({ ...p, showAbove: v }))} />
                                {view.showAbove && (
                                    <MiniSlider testId="above-opacity" label="Above opacity" value={Math.round(view.aboveOpacity * 100)} min={0} max={100} step={5} onChange={(v) => setView((p) => ({ ...p, aboveOpacity: v / 100 }))} format={(v) => `${v}%`} />
                                )}
                            </>
                        )}
                        {showingDoc && (
                            <p className="text-[10px] text-muted-foreground leading-snug" data-testid="document-hint">
                                {init.mode === "update" && showingDoc.frame ? "The layer keeps its place in the document." : "The model is placed exactly where you see it."}
                                {!showingDoc.below && !showingDoc.above && " The document has no other visible layers."}
                                {environmentBackground && " The environment background covers the layers below."}
                                {enlarged > 1.25 && ` The render is enlarged ${enlarged.toFixed(1)}× in the document; a higher export resolution keeps it sharp.`}
                            </p>
                        )}
                    </div>

                    <SectionTitle icon={<Wand2 size={12} />}>Light presets</SectionTitle>
                    <div className="grid grid-cols-2 gap-1.5">
                        {LIGHT_PRESETS.map((preset) => (
                            <ChipButton key={preset.name} active={activePreset === preset.name} onClick={() => applyPreset(preset)}>
                                <span className="w-2.5 h-2.5 rounded-full shrink-0 border border-black/10" style={{ backgroundColor: preset.swatch }} />
                                <span className="flex-1">{preset.name}</span>
                            </ChipButton>
                        ))}
                    </div>

                    <SectionTitle icon={<Sun size={12} />}>Light</SectionTitle>
                    <div className="space-y-2.5">
                        <MiniToggle label="Show sun widget" checked={gizmoVisible} onChange={setGizmoVisible} />
                        <MiniSlider label="Intensity" value={lightIntensity} min={0} max={5} step={0.05} onChange={setLightIntensity} format={(v) => v.toFixed(2)} />
                        <MiniSlider label="Distance" value={lightDistance} min={2} max={15} step={0.1} onChange={(d) => setLightPosition(vecScaleTo(lightPosition, d))} format={(v) => v.toFixed(1)} />
                        <MiniSlider label="Ambient" value={ambientIntensity} min={0} max={1.5} step={0.05} onChange={setAmbientIntensity} format={(v) => v.toFixed(2)} />
                        <ColorField value={lightColor} onChange={(c) => (setActivePreset(null), setLightColor(c))} />
                    </div>

                    <SectionTitle icon={<Palette size={12} />}>Environment</SectionTitle>
                    <div className="space-y-2.5">
                        <Dropdown value={environment} options={ENVIRONMENTS.map((env) => ({ value: env as string, label: env[0].toUpperCase() + env.slice(1) }))} onChange={setEnvironment} ariaLabel="Environment" testId="environment" />
                        <MiniSlider label="Env intensity" value={envIntensity} min={0} max={2} step={0.05} onChange={setEnvIntensity} format={(v) => v.toFixed(2)} />
                        <MiniToggle label="Show as background" checked={environmentBackground} onChange={setEnvironmentBackground} />
                    </div>

                    <SectionTitle icon={<Sun size={12} />}>Shadows</SectionTitle>
                    <div className="space-y-2.5">
                        <MiniToggle label="Cast shadow" checked={castShadowEnabled} onChange={setCastShadowEnabled} />
                        {castShadowEnabled && (
                            <>
                                <MiniSlider label="Cast blur" value={castShadowBlur} min={0} max={60} step={1} onChange={setCastShadowBlur} />
                                <MiniSlider label="Cast intensity" value={castShadowIntensity} min={0} max={1} step={0.05} onChange={setCastShadowIntensity} format={(v) => v.toFixed(2)} />
                            </>
                        )}
                        <MiniToggle label="Contact shadow" checked={contactShadowEnabled} onChange={setContactShadowEnabled} />
                        {contactShadowEnabled && (
                            <>
                                <MiniSlider label="Contact blur" value={contactShadowBlur} min={0} max={20} step={1} onChange={setContactShadowBlur} />
                                <MiniSlider label="Contact intensity" value={contactShadowIntensity} min={0} max={1} step={0.05} onChange={setContactShadowIntensity} format={(v) => v.toFixed(2)} />
                            </>
                        )}
                    </div>

                    <SectionTitle
                        icon={<Box size={12} />}
                        right={
                            <button type="button" onClick={resetPose} className="text-muted-foreground hover:text-foreground" title="Reset pose">
                                <RotateCcw size={11} />
                            </button>
                        }
                    >
                        Pose
                    </SectionTitle>
                    <div className="space-y-2.5">
                        <MiniSlider testId="rotate-y" label="Turn (Y)" value={rotY} min={-180} max={180} step={1} onChange={setRotY} format={(v) => `${v}°`} />
                        <MiniSlider label="Tilt (X)" value={rotX} min={-180} max={180} step={1} onChange={setRotX} format={(v) => `${v}°`} />
                        <MiniSlider label="Roll (Z)" value={rotZ} min={-180} max={180} step={1} onChange={setRotZ} format={(v) => `${v}°`} />
                        <MiniSlider label="Scale" value={modelScale} min={0.2} max={3} step={0.05} onChange={setModelScale} format={(v) => `${v.toFixed(2)}×`} />
                    </div>

                    <SectionTitle icon={<Camera size={12} />}>Camera</SectionTitle>
                    <div className="grid grid-cols-2 gap-1.5">
                        {CAMERA_VIEWS.map((view) => (
                            <ChipButton key={view.name} onClick={() => applyCameraView(view.direction)}>
                                {view.name}
                            </ChipButton>
                        ))}
                        <ChipButton onClick={resetCamera}>Reset</ChipButton>
                    </div>
                    <div className="mt-2.5">
                        <MiniSlider label="Field of view" value={fov} min={10} max={90} step={1} onChange={setFov} format={(v) => `${v}°`} />
                    </div>

                    <SectionTitle icon={<Monitor size={12} />}>Export resolution</SectionTitle>
                    <div className="space-y-2.5">
                        <div className="grid grid-cols-2 gap-2">
                            {(["width", "height"] as const).map((dim) => (
                                <label key={dim} className="block">
                                    <span className="text-muted-foreground block mb-1 text-[10px] uppercase">{dim}</span>
                                    <input
                                        type="number"
                                        min={64}
                                        max={8192}
                                        value={resolution[dim]}
                                        onChange={(e) => setResolution((r) => ({ ...r, [dim]: parseInt(e.target.value, 10) || r[dim] }))}
                                        onBlur={() => setResolution((r) => clampResolution(r))}
                                        className="w-full bg-input px-2 py-1 rounded border border-border text-right"
                                    />
                                </label>
                            ))}
                        </div>
                        <div className="grid grid-cols-4 gap-1">
                            {RESOLUTION_PRESETS.map((size) => (
                                <ChipButton key={size} active={resolution.width === size && resolution.height === size} onClick={() => setResolution({ width: size, height: size })}>
                                    {size}
                                </ChipButton>
                            ))}
                        </div>
                        {doc && (
                            <ChipButton active={resolution.width === Math.min(8192, doc.width) && resolution.height === Math.min(8192, doc.height)} onClick={() => setResolution(clampResolution({ width: doc.width, height: doc.height }))} title={doc.title}>
                                <ImageIcon size={11} /> Match document ({doc.width}×{doc.height})
                            </ChipButton>
                        )}
                    </div>
                </aside>
            </div>

            <footer className="px-4 py-3 border-t border-border flex items-center gap-3 bg-card shrink-0">
                <div className="flex-1 min-w-0 text-[11px] text-muted-foreground truncate" data-testid="model-info">
                    <span className="text-foreground font-medium">{init.model.name}</span>
                    {modelInfo && ` · ${modelInfo.meshes} mesh${modelInfo.meshes === 1 ? "" : "es"} · ${modelInfo.triangles.toLocaleString()} triangles`}
                    {` · ${resolution.width}×${resolution.height} px`}
                    {error && <span className="text-danger ml-2">{error}</span>}
                </div>
                <button type="button" onClick={onCancel} className="px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-secondary rounded-lg transition-colors flex items-center gap-1.5">
                    <X size={15} /> Cancel
                </button>
                <button
                    type="button"
                    data-testid="editor-ok"
                    onClick={() => void handleOk()}
                    disabled={!gl || busy || !!loadFailed || !modelInfo}
                    className="px-6 py-2 text-sm font-semibold bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-40 flex items-center gap-2"
                >
                    <Check size={16} />
                    {busy ? "Rendering…" : init.mode === "update" ? "Update Layer" : "Place in Document"}
                </button>
            </footer>
        </div>
    );
}
