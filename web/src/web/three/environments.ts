/**
 * Lighting environments for the editor and previews.
 *
 * Same ten looks as the ImageExpress editor (drei presets), but loaded from
 * @pmndrs/assets (CC0 Poly Haven HDRIs as small embedded EXRs) instead of drei's CDN,
 * so the editor works offline and inside Photoshop's WebView without network access.
 * Each file is its own chunk and only loads when chosen.
 */
import { useEffect, useState } from "react";
import type { EnvironmentName } from "@shared/threeD";

const LOADERS: Record<EnvironmentName, () => Promise<{ default: string }>> = {
    studio: () => import("@pmndrs/assets/hdri/studio.exr"),
    city: () => import("@pmndrs/assets/hdri/city.exr"),
    apartment: () => import("@pmndrs/assets/hdri/apartment.exr"),
    dawn: () => import("@pmndrs/assets/hdri/dawn.exr"),
    sunset: () => import("@pmndrs/assets/hdri/sunset.exr"),
    forest: () => import("@pmndrs/assets/hdri/forest.exr"),
    park: () => import("@pmndrs/assets/hdri/park.exr"),
    night: () => import("@pmndrs/assets/hdri/night.exr"),
    lobby: () => import("@pmndrs/assets/hdri/lobby.exr"),
    warehouse: () => import("@pmndrs/assets/hdri/warehouse.exr"),
};

const cache = new Map<string, Promise<string>>();

export function loadEnvironment(name: string): Promise<string> {
    const key = (name in LOADERS ? name : "city") as EnvironmentName;
    let p = cache.get(key);
    if (!p) {
        p = LOADERS[key]().then((m) => m.default);
        cache.set(key, p);
    }
    return p;
}

/** Data URL of an environment, or null while it loads. */
export function useEnvironmentUrl(name: string): string | null {
    const [url, setUrl] = useState<string | null>(null);
    useEffect(() => {
        let live = true;
        loadEnvironment(name).then((u) => live && setUrl(u));
        return () => {
            live = false;
        };
    }, [name]);
    return url;
}
