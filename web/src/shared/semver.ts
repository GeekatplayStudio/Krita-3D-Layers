/**
 * Minimal semantic-version handling for the update check ("v1.2.3", "1.2.3-beta.2").
 * Only what GitHub release tags need: parse, compare, and prerelease detection.
 */

export type SemVer = { major: number; minor: number; patch: number; pre: (string | number)[] };

export function parseVersion(input: string): SemVer | null {
    const m = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec(input.trim());
    if (!m) return null;
    const pre = m[4] ? m[4].split(".").map((p) => (/^\d+$/.test(p) ? Number(p) : p)) : [];
    return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]), pre };
}

/** -1 when a < b, 0 when equal, 1 when a > b. Unparseable versions sort lowest. */
export function compareVersions(a: string, b: string): number {
    const va = parseVersion(a);
    const vb = parseVersion(b);
    if (!va || !vb) return va ? 1 : vb ? -1 : 0;
    for (const k of ["major", "minor", "patch"] as const) {
        if (va[k] !== vb[k]) return va[k] < vb[k] ? -1 : 1;
    }
    // A version without prerelease tags is newer than the same version with them.
    if (!va.pre.length || !vb.pre.length) return va.pre.length === vb.pre.length ? 0 : va.pre.length ? -1 : 1;
    for (let i = 0; i < Math.max(va.pre.length, vb.pre.length); i++) {
        const x = va.pre[i];
        const y = vb.pre[i];
        if (x === undefined) return -1;
        if (y === undefined) return 1;
        if (x === y) continue;
        if (typeof x === "number" && typeof y === "number") return x < y ? -1 : 1;
        if (typeof x === "number") return -1;
        if (typeof y === "number") return 1;
        return x < y ? -1 : 1;
    }
    return 0;
}

export const isPrerelease = (v: string) => (parseVersion(v)?.pre.length ?? 0) > 0;
