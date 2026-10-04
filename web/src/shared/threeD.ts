/**
 * 3D layer data shared by the editor (WebView) and the host (layer metadata).
 *
 * Ported from ImageExpress (`src/types.ts` ThreeDSettings and
 * `src/components/three/threeDLayerPresets.ts`) so a layer posed here renders the
 * same way it does there. Pure data plus the vector helpers the presets need.
 */

export type Vec3 = { x: number; y: number; z: number };

/** Everything needed to re-render a 3D layer exactly as it was last saved. */
export type ThreeDSettings = {
    lightPosition: Vec3;
    lightIntensity: number;
    lightColor: string;
    castShadowEnabled: boolean;
    castShadowBlur: number;
    castShadowIntensity: number;
    contactShadowEnabled: boolean;
    contactShadowBlur: number;
    contactShadowIntensity: number;
    resolution: { width: number; height: number };
    cameraPosition?: Vec3;
    cameraTarget?: Vec3;
    /** Vertical field of view in degrees (the ImageExpress editor always used 45). */
    cameraFov?: number;
    ambientIntensity?: number;
    environment?: string;
    envIntensity?: number;
    /** Show the environment map as a visible background instead of transparency. */
    environmentBackground?: boolean;
    modelRotationX?: number;
    modelRotationY?: number;
    modelRotationZ?: number;
    modelScale?: number;
};

/**
 * Lighting remembered across sessions and applied when a NEW model is opened.
 * Layers reopened from the document keep the settings saved on the layer.
 */
export type LightingDefaults = Pick<
    ThreeDSettings,
    | "lightPosition"
    | "lightIntensity"
    | "lightColor"
    | "castShadowEnabled"
    | "castShadowBlur"
    | "castShadowIntensity"
    | "contactShadowEnabled"
    | "contactShadowBlur"
    | "contactShadowIntensity"
> & {
    ambientIntensity: number;
    environment: string;
    envIntensity: number;
};

export const DEFAULT_LIGHTING: LightingDefaults = {
    lightPosition: { x: 5, y: 5, z: 5 },
    lightIntensity: 1.2,
    lightColor: "#ffffff",
    ambientIntensity: 0.35,
    environment: "city",
    envIntensity: 0.6,
    castShadowEnabled: true,
    castShadowBlur: 22,
    castShadowIntensity: 0.35,
    contactShadowEnabled: true,
    contactShadowBlur: 8,
    contactShadowIntensity: 0.6,
};

export const GIZMO_ORBIT_RADIUS = 2.2;
export const GIZMO_GROUP_NAME = "light-gizmo-group";

export type LightPreset = {
    name: string;
    swatch: string;
    direction: Vec3;
    intensity: number;
    color: string;
    ambient: number;
};

export const LIGHT_PRESETS: LightPreset[] = [
    { name: "Studio", swatch: "#f5f5f5", direction: { x: 4, y: 6, z: 4 }, intensity: 1.3, color: "#ffffff", ambient: 0.4 },
    { name: "Golden Hour", swatch: "#ffb36b", direction: { x: 6, y: 1.6, z: 3 }, intensity: 1.6, color: "#ffb36b", ambient: 0.3 },
    { name: "Noon", swatch: "#fff3c4", direction: { x: 0.5, y: 8, z: 2 }, intensity: 1.8, color: "#fff7e0", ambient: 0.5 },
    { name: "Dramatic", swatch: "#c9c9c9", direction: { x: -6, y: 4, z: -1.5 }, intensity: 2.2, color: "#ffffff", ambient: 0.12 },
    { name: "Rim", swatch: "#cfe4ff", direction: { x: 0, y: 3, z: -7 }, intensity: 2.4, color: "#cfe4ff", ambient: 0.2 },
    { name: "Soft", swatch: "#efeae2", direction: { x: 3, y: 5, z: 5 }, intensity: 0.9, color: "#fff6ec", ambient: 0.7 },
    { name: "Moonlight", swatch: "#7ea0ff", direction: { x: -4, y: 3.5, z: 4 }, intensity: 1.1, color: "#8fa8ff", ambient: 0.15 },
];

export const ENVIRONMENTS = ["studio", "city", "apartment", "dawn", "sunset", "forest", "park", "night", "lobby", "warehouse"] as const;
export type EnvironmentName = (typeof ENVIRONMENTS)[number];

export const CAMERA_VIEWS: { name: string; direction: Vec3 }[] = [
    { name: "Front", direction: { x: 0, y: 0.25, z: 1 } },
    { name: "¾ Left", direction: { x: -1, y: 0.45, z: 1 } },
    { name: "¾ Right", direction: { x: 1, y: 0.45, z: 1 } },
    { name: "Side", direction: { x: 1, y: 0.15, z: 0 } },
    { name: "Top", direction: { x: 0.01, y: 1, z: 0.15 } },
];

export const RESOLUTION_PRESETS = [512, 1024, 2048, 4096] as const;
export const MAX_RESOLUTION = 8192;
export const DEFAULT_CAMERA_POSITION: Vec3 = { x: 0, y: 0, z: 4 };
export const DEFAULT_CAMERA_FOV = 45;

/** Euclidean length, never zero so it is always safe to divide by. */
export const vecLength = (v: Vec3) => Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z) || 1;

/** Rescale a direction to a fixed length, preserving its orientation. */
export const vecScaleTo = (v: Vec3, length: number): Vec3 => {
    const l = vecLength(v);
    return { x: (v.x / l) * length, y: (v.y / l) * length, z: (v.z / l) * length };
};

export type ModelBounds = { groundY: number; radius: number };

/** Clamps an export resolution to what the renderer and Photoshop can handle. */
export function clampResolution(size: { width: number; height: number }): { width: number; height: number } {
    const clamp = (v: number) => (Number.isFinite(v) ? Math.min(MAX_RESOLUTION, Math.max(64, Math.round(v))) : 2048);
    return { width: clamp(size.width), height: clamp(size.height) };
}

/** Builds full settings for a new model from remembered lighting and an export size. */
export function settingsForNewModel(lighting: Partial<LightingDefaults> | undefined, resolution: number): ThreeDSettings {
    const l = { ...DEFAULT_LIGHTING, ...(lighting ?? {}) };
    return {
        ...l,
        resolution: clampResolution({ width: resolution, height: resolution }),
        cameraPosition: { ...DEFAULT_CAMERA_POSITION },
        cameraTarget: { x: 0, y: 0, z: 0 },
        cameraFov: DEFAULT_CAMERA_FOV,
        environmentBackground: false,
        modelRotationX: 0,
        modelRotationY: 0,
        modelRotationZ: 0,
        modelScale: 1,
    };
}

/** Extracts the lighting part of full settings (what gets remembered as defaults). */
export function lightingOf(s: ThreeDSettings): LightingDefaults {
    return {
        lightPosition: s.lightPosition,
        lightIntensity: s.lightIntensity,
        lightColor: s.lightColor,
        ambientIntensity: s.ambientIntensity ?? DEFAULT_LIGHTING.ambientIntensity,
        environment: s.environment ?? DEFAULT_LIGHTING.environment,
        envIntensity: s.envIntensity ?? DEFAULT_LIGHTING.envIntensity,
        castShadowEnabled: s.castShadowEnabled,
        castShadowBlur: s.castShadowBlur,
        castShadowIntensity: s.castShadowIntensity,
        contactShadowEnabled: s.contactShadowEnabled,
        contactShadowBlur: s.contactShadowBlur,
        contactShadowIntensity: s.contactShadowIntensity,
    };
}
