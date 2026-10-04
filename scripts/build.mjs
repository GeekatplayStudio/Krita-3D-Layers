// Builds the 3D editor and the task page into plugin/geekatplay_3d_layers/web.
//   npm run build
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const version = /__version__ = "([^"]+)"/.exec(readFileSync(join(root, "plugin/geekatplay_3d_layers/__init__.py"), "utf8"))[1];
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
if (pkg.version !== version) {
    console.error(`package.json says ${pkg.version} but the plugin says ${version}; make them the same.`);
    process.exit(1);
}
console.log(`Building Geekatplay 3D Layers for Krita ${version}`);
execSync("npx vite build --config vite.config.ts --logLevel warn", { cwd: root, stdio: "inherit" });
console.log("  ✓ web → plugin/geekatplay_3d_layers/web");
