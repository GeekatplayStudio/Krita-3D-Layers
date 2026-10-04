// Packs the release ZIP. The same file works two ways:
// - Krita's Tools › Scripts › Import Python Plugin from File (it takes the .desktop file and the
//   geekatplay_3d_layers folder from the ZIP's root and ignores the rest);
// - unzip and double-click "Install on Windows.cmd" / "Install on macOS.command".
//   npm run package   →  dist/Geekatplay-3D-Layers-Krita-<version>.zip (+ .sha256)
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { zipSync } from "fflate";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const plugin = join(root, "plugin");
const version = /__version__ = "([^"]+)"/.exec(readFileSync(join(plugin, "geekatplay_3d_layers/__init__.py"), "utf8"))[1];
if (!existsSync(join(plugin, "geekatplay_3d_layers/web/editor.html"))) {
    console.error("The web part is not built; run npm run build first.");
    process.exit(1);
}

const files = {};
const EXECUTABLE = { os: 3, attrs: 0o100755 << 16 };
const crlf = (text) => new TextEncoder().encode(text.replace(/\r?\n/g, "\r\n"));
function add(dir) {
    for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (name === "__pycache__" || name.endsWith(".pyc") || name.endsWith(".map")) continue;
        if (statSync(path).isDirectory()) add(path);
        else files[relative(plugin, path).split("\\").join("/")] = new Uint8Array(readFileSync(path));
    }
}
add(plugin);
for (const required of ["geekatplay_3d_layers.desktop", "geekatplay_3d_layers/__init__.py", "geekatplay_3d_layers/Manual.html", "geekatplay_3d_layers/web/editor.html", "geekatplay_3d_layers/web/tasks.html", "geekatplay_3d_layers/samples/sample-rocket.glb"]) {
    if (!files[required]) {
        console.error(`Missing ${required}`);
        process.exit(1);
    }
}
const install = (name) => readFileSync(join(root, "install", name), "utf8");
files["Install on Windows.cmd"] = crlf(install("Install on Windows.cmd"));
files["Uninstall on Windows.cmd"] = crlf(install("Uninstall on Windows.cmd"));
files["Install on macOS.command"] = [new TextEncoder().encode(install("Install on macOS.command")), EXECUTABLE];
files["Install on Linux.sh"] = [new TextEncoder().encode(install("Install on Linux.sh")), EXECUTABLE];
files["install/install-windows.ps1"] = crlf(install("install-windows.ps1"));
files["install/install-unix.sh"] = [new TextEncoder().encode(install("install-unix.sh")), EXECUTABLE];
files["README.txt"] = crlf(install("README.txt"));
files["LICENSE.txt"] = crlf(readFileSync(join(root, "LICENSE"), "utf8"));

const zip = zipSync(files, { level: 9 });
mkdirSync(join(root, "dist"), { recursive: true });
const name = `Geekatplay-3D-Layers-Krita-${version}.zip`;
const out = join(root, "dist", name);
writeFileSync(out, zip);
const sha = createHash("sha256").update(zip).digest("hex");
writeFileSync(`${out}.sha256`, `${sha}  ${name}\n`);
console.log(`Packaged ${Object.keys(files).length} files, ${(zip.length / 1e6).toFixed(2)} MB → dist/${name} (sha256 ${sha.slice(0, 16)}…)`);
