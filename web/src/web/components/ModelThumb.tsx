/**
 * Library thumbnail. Uses the stored preview image; when a model has none (ComfyUI and
 * imported files never come with one), renders it once with three.js and asks the host
 * to save the PNG next to the model, so the next panel load is instant.
 */
import { useEffect, useState } from "react";
import { Box as BoxIcon } from "lucide-react";
import type { LibraryItem } from "@shared/types";
import { bridge } from "../bridge/client";
import { imageUrl, modelUrl } from "../three/modelSource";
import { renderModelThumbnail } from "../three/thumbnail";

const rendering = new Set<string>();

export function ModelThumb({ item, baseUrl, autoRender = true, className = "" }: { item: LibraryItem; baseUrl: string | null; autoRender?: boolean; className?: string }) {
    const [src, setSrc] = useState<string | null>(null);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
        let live = true;
        setFailed(false);
        (async () => {
            if (item.thumbFile) {
                const url = await imageUrl(baseUrl, item.thumbFile);
                if (live) setSrc(url.startsWith("data:") || url.startsWith("blob:") ? url : `${url}?v=${item.importedAt}-${item.thumbFile}`);
                return;
            }
            if (!autoRender || rendering.has(item.id)) return;
            rendering.add(item.id);
            try {
                const dataUrl = await renderModelThumbnail(await modelUrl(baseUrl, item.modelFile), 512);
                if (live) setSrc(dataUrl);
                await bridge().call("library.saveThumbnail", { id: item.id, pngBase64: dataUrl.replace(/^data:[^,]*,/, "") });
            } catch (err) {
                if (live) setFailed(true);
                void bridge().call("log.write", { level: "warn", message: `Thumbnail for ${item.name} failed`, data: String((err as Error).message ?? err) });
            } finally {
                rendering.delete(item.id);
            }
        })();
        return () => {
            live = false;
        };
    }, [item.id, item.thumbFile, item.modelFile, item.importedAt, baseUrl, autoRender, item.name]);

    return (
        <div className={`relative bg-background flex items-center justify-center overflow-hidden ${className}`}>
            {src && !failed ? (
                <img src={src} alt={item.name} className="w-full h-full object-contain" draggable={false} onError={() => setFailed(true)} />
            ) : (
                <BoxIcon size={28} className={`text-muted-foreground ${!failed && !item.thumbFile && autoRender ? "animate-pulse" : ""}`} />
            )}
        </div>
    );
}
