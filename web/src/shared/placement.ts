/**
 * Geometry for placing a render into a document (pure, unit-tested).
 *
 * A render is a fixed-size frame (e.g. 2048×2048) with the model somewhere inside
 * and transparent space around it. The frame — not the visible object — is what the
 * smart object holds, so later re-renders at the same size slot into the same place.
 */
export type Box = { left: number; top: number; right: number; bottom: number };

export const boxWidth = (b: Box) => b.right - b.left;
export const boxHeight = (b: Box) => b.bottom - b.top;

/**
 * Where the render frame must go (document pixels) so the object inside it
 * (`content`, in render pixels) fits centred inside `target`.
 */
export function frameForTarget(render: { width: number; height: number }, content: Box | undefined, target: Box): Box {
    const c = content && boxWidth(content) > 0 && boxHeight(content) > 0 ? content : { left: 0, top: 0, right: render.width, bottom: render.height };
    const scale = Math.min(boxWidth(target) / boxWidth(c), boxHeight(target) / boxHeight(c));
    const cx = (c.left + c.right) / 2;
    const cy = (c.top + c.bottom) / 2;
    const tx = (target.left + target.right) / 2;
    const ty = (target.top + target.bottom) / 2;
    const left = tx - cx * scale;
    const top = ty - cy * scale;
    return { left, top, right: left + render.width * scale, bottom: top + render.height * scale };
}

/** Default target for a new 3D layer: the middle `fraction` of the canvas. */
export function centeredTarget(docWidth: number, docHeight: number, fraction = 0.6): Box {
    const w = docWidth * fraction;
    const h = docHeight * fraction;
    return { left: (docWidth - w) / 2, top: (docHeight - h) / 2, right: (docWidth + w) / 2, bottom: (docHeight + h) / 2 };
}

/** Percent scale + offset that turn the frame `current` into `desired` (uniform scale). */
export function transformBetween(current: Box, desired: Box): { scalePercent: number } {
    const s = boxWidth(current) > 0 ? boxWidth(desired) / boxWidth(current) : 1;
    return { scalePercent: s * 100 };
}

/** Bounding box of pixels with alpha > threshold in RGBA data; undefined when fully transparent. */
export function alphaBounds(rgba: Uint8Array | Uint8ClampedArray, width: number, height: number, threshold = 8): Box | undefined {
    let left = width;
    let top = height;
    let right = -1;
    let bottom = -1;
    for (let y = 0; y < height; y++) {
        const row = y * width * 4;
        for (let x = 0; x < width; x++) {
            if (rgba[row + x * 4 + 3] > threshold) {
                if (x < left) left = x;
                if (x > right) right = x;
                if (y < top) top = y;
                if (y > bottom) bottom = y;
            }
        }
    }
    return right < 0 ? undefined : { left, top, right: right + 1, bottom: bottom + 1 };
}
