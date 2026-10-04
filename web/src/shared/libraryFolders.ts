/**
 * Library folders are virtual: a folder is a path such as "Characters/Robots" stored on each
 * model (LibraryItem.folder) plus the list of folders in library/index.json (so empty
 * folders exist too). Model files stay in library/<id>/, so moving models between folders
 * never touches the disk and never breaks a placed 3D layer, which refers to the model by id.
 * "" is the top level of the library.
 */

/** Characters a folder name may not contain ("/" separates levels). */
const BAD_NAME = /[/\\:*?"<>|\u0000-\u001f]/g;
export const MAX_FOLDER_NAME = 60;

/** A clean folder name, or "" when nothing usable is left. */
export function cleanFolderName(name: string): string {
    return name.replace(BAD_NAME, " ").replace(/\s+/g, " ").trim().slice(0, MAX_FOLDER_NAME).trim();
}

/** "  A / /B\\C " → "A/B/C" (each segment cleaned; empty segments dropped). */
export function normalizeFolder(path: unknown): string {
    if (typeof path !== "string") return "";
    return path
        .split(/[/\\]+/)
        .map(cleanFolderName)
        .filter(Boolean)
        .join("/");
}

export const joinFolder = (parent: string, child: string): string => normalizeFolder(parent ? `${parent}/${child}` : child);
export const parentFolder = (path: string): string => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
export const folderName = (path: string): string => path.slice(path.lastIndexOf("/") + 1);

/** True when `path` is `folder` or inside it. */
export const isInFolder = (path: string, folder: string): boolean => !folder || path === folder || path.startsWith(`${folder}/`);

/** "A/B/C" → ["A", "A/B", "A/B/C"]. */
export function withAncestors(path: string): string[] {
    const parts = normalizeFolder(path).split("/").filter(Boolean);
    return parts.map((_, i) => parts.slice(0, i + 1).join("/"));
}

/** Direct subfolders of `parent` among `folders`. */
export function childFolders(folders: readonly string[], parent: string): string[] {
    return folders.filter((f) => parentFolder(f) === parent && f !== parent).sort((a, b) => folderName(a).localeCompare(folderName(b), undefined, { sensitivity: "base", numeric: true }));
}

/** Moves `path` (a folder, or an item's folder) from under `from` to under `to`: "A/B/x", A/B → C gives "C/x". */
export function rebase(path: string, from: string, to: string): string {
    if (path === from) return to;
    return joinFolder(to, path.slice(from.length + 1));
}

/** "A/B" → "Library › A › B". */
export const folderLabel = (path: string): string => (path ? `Library › ${path.split("/").join(" › ")}` : "Library");

/** Every folder: the stored ones, the folders of items, and all their parents. Sorted. */
export function allFolders(stored: Iterable<string>, items: readonly { folder?: string }[]): string[] {
    const all = new Set<string>();
    for (const f of [...stored, ...items.map((i) => i.folder ?? "")]) for (const a of withAncestors(f)) all.add(a);
    return [...all].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base", numeric: true }));
}

/**
 * Moves everything at or under folder `from` to `to` (rename: same parent, new name; delete:
 * `to` = the parent). Updates the items in place and returns the new stored-folder set.
 */
export function relocateFolder(stored: Iterable<string>, items: { folder?: string }[], from: string, to: string): Set<string> {
    const next = new Set<string>();
    for (const f of stored) {
        const moved = isInFolder(f, from) ? rebase(f, from, to) : f;
        if (moved) next.add(moved);
    }
    for (const item of items) {
        const f = item.folder ?? "";
        if (!f || !isInFolder(f, from)) continue;
        const moved = rebase(f, from, to);
        if (moved) item.folder = moved;
        else delete item.folder;
    }
    if (to) for (const a of withAncestors(to)) next.add(a);
    return next;
}
