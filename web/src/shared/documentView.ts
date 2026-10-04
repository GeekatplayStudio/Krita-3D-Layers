/**
 * "Show document" in the 3D editor (pure, unit-tested).
 *
 * The editor can show the Photoshop document around the model: the visible layers under
 * the 3D layer behind it, and the layers above it in front. The host reads the two
 * composites by hiding one part of the layer stack at a time (`splitLayers`), and the
 * editor maps the document onto its viewport (`viewRegion`, `documentRect`), which always
 * has the aspect ratio of the render.
 */
import type { Box } from "./placement";

/** A layer as far as the split is concerned: groups have `layers`, listed top first. */
export type LayerNode = { id: number; visible: boolean; layers?: LayerNode[] };

export type LayerSplit = {
    /** Visible layers to hide so that only what is above the split shows. */
    hideForAbove: number[];
    /** Visible layers to hide so that only what is below the split shows. */
    hideForBelow: number[];
    /** False when the split layer is not in the tree (everything counts as below). */
    found: boolean;
    /** Whether any visible layer is above / below the split (the split layer itself not counted when it is hidden in both). */
    hasAbove: boolean;
    hasBelow: boolean;
};

function contains(node: LayerNode, id: number): boolean {
    return node.id === id || !!node.layers?.some((child) => contains(child, id));
}

/**
 * Splits the layer stack at layer `splitId`. Only whole subtrees are hidden: a group that
 * holds the split layer stays visible and is split inside. The split layer itself goes
 * with the layers below when `splitBelongsBelow` (a new layer is placed above the active
 * one), and is hidden in both parts otherwise (the 3D layer being edited).
 * Without `splitId`, or when it is not found, everything visible counts as below.
 */
export function splitLayers(layers: LayerNode[], splitId: number | undefined, splitBelongsBelow: boolean): LayerSplit {
    const hideForAbove: number[] = [];
    const hideForBelow: number[] = [];
    const found = splitId !== undefined && layers.some((l) => contains(l, splitId));
    const walk = (nodes: LayerNode[]) => {
        let below = false;
        for (const node of nodes) {
            if (!node.visible) {
                if (found && !below && contains(node, splitId!)) below = true;
                continue;
            }
            if (below || !found) {
                hideForAbove.push(node.id);
            } else if (node.id === splitId) {
                below = true;
                hideForAbove.push(node.id);
                if (!splitBelongsBelow) hideForBelow.push(node.id);
            } else if (contains(node, splitId!)) {
                below = true;
                walk(node.layers ?? []);
            } else {
                hideForBelow.push(node.id);
            }
        }
    };
    walk(layers);
    const own = (id: number) => id === splitId && !splitBelongsBelow;
    return { hideForAbove, hideForBelow, found, hasAbove: hideForBelow.some((id) => !own(id)), hasBelow: hideForAbove.some((id) => !own(id)) };
}

/**
 * The part of the document (document pixels) that the render covers.
 * - `frame` (a 3D layer being edited): the layer keeps its left, top and width when it is
 *   updated, so a different aspect ratio only changes the height.
 * - Otherwise the whole canvas, centred, with the render's aspect ratio: the render may
 *   reach past the canvas on two sides, never crop it.
 */
export function viewRegion(doc: { width: number; height: number }, render: { width: number; height: number }, frame?: Box): Box {
    const aspect = render.width / render.height;
    if (frame && frame.right - frame.left > 0) {
        const width = frame.right - frame.left;
        return { left: frame.left, top: frame.top, right: frame.right, bottom: frame.top + width / aspect };
    }
    if (doc.width / doc.height > aspect) {
        const height = doc.width / aspect;
        const top = (doc.height - height) / 2;
        return { left: 0, top, right: doc.width, bottom: top + height };
    }
    const width = doc.height * aspect;
    const left = (doc.width - width) / 2;
    return { left, top: 0, right: left + width, bottom: doc.height };
}

/** Where the document canvas goes inside a viewport of `size` that shows `region`, in viewport pixels. */
export function documentRect(doc: { width: number; height: number }, region: Box, size: { width: number; height: number }) {
    const sx = size.width / (region.right - region.left);
    const sy = size.height / (region.bottom - region.top);
    return { left: -region.left * sx, top: -region.top * sy, width: doc.width * sx, height: doc.height * sy };
}

/** How much the render is enlarged when placed over `region` (above ~1.25 it looks soft). */
export function placementScale(region: Box, render: { width: number }): number {
    return (region.right - region.left) / render.width;
}
