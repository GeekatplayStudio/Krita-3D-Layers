// Copies the 3D editor, the model converter and their shared code from the Photoshop plugin
// (https://github.com/GeekatplayStudio/Photoshop-3D), so both plugins use the same editor.
//
//   node scripts/sync-web.mjs [path to the Photoshop-3D checkout]   (default: ../Photoshop-3D-plugin)
//
// Files the Krita plugin changes are listed in KRITA_OWNED and are never overwritten.
import { cpSync, existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(process.argv[2] ?? process.env.PS3D_REPO ?? join(root, "..", "Photoshop-3D-plugin"));
if (!existsSync(join(source, "src", "web", "editor"))) {
    console.error(`Not a Photoshop-3D checkout: ${source}`);
    process.exit(1);
}

/** Paths (relative to web/) the Krita plugin owns. */
const KRITA_OWNED = new Set(["src/web/bridge/client.ts", "src/web/bridge/httpTransport.ts", "src/web/editor/main.tsx", "src/web/tasks.html", "src/web/tasks/main.tsx"]);

const COPY = [
    "src/shared",
    "src/web/editor",
    "src/web/three",
    "src/web/components",
    "src/web/bridge",
    "src/web/panel/importModels.ts",
    "src/web/styles.css",
    "src/web/editor.html",
    "src/web/env.d.ts",
    "tests/fixtures/public/samples",
];

let copied = 0;
function copy(rel) {
    const from = join(source, rel);
    if (!existsSync(from)) return;
    if (statSync(from).isDirectory()) {
        for (const name of readdirSync(from)) copy(join(rel, name).replace(/\\/g, "/"));
        return;
    }
    if (/\.test\.tsx?$/.test(rel)) return;
    const target = rel.startsWith("tests/") ? join(root, rel) : join(root, "web", rel);
    const owned = relative(join(root, "web"), target).replace(/\\/g, "/");
    if (KRITA_OWNED.has(owned) && existsSync(target)) return;
    mkdirSync(dirname(target), { recursive: true });
    cpSync(from, target);
    copied++;
}
for (const rel of COPY) copy(rel);
console.log(`Copied ${copied} files from ${source}`);
