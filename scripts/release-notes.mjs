// Prints the CHANGELOG.md section of a version, plus install steps, for the GitHub release.
//   node scripts/release-notes.mjs 0.1.0
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const version = process.argv[2];
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const changelog = readFileSync(join(root, "CHANGELOG.md"), "utf8");
const start = changelog.indexOf(`## [${version}]`);
if (start < 0) {
    console.error(`CHANGELOG.md has no section for ${version}`);
    process.exit(1);
}
const rest = changelog.slice(start);
const next = rest.indexOf("\n## [", 1);
const section = (next < 0 ? rest : rest.slice(0, next)).split("\n").slice(1).join("\n").trim();

console.log(`${section}

## Install

1. Download **Geekatplay-3D-Layers-Krita-${version}.zip** below and close Krita.
2. Unzip it and double-click **Install on Windows.cmd** (Mac: **Install on macOS.command**; Linux: \`sh "Install on Linux.sh"\`).
   Or in Krita: **Tools › Scripts › Import Python Plugin from File…**, choose the ZIP, enable it, restart Krita.
3. Open Krita and choose **Settings › Dockers › 3D Layers**.

Requires Krita 5.2 or newer. Full instructions: [README](https://github.com/GeekatplayStudio/Krita-3D-Layers#install) · [User guide](https://github.com/GeekatplayStudio/Krita-3D-Layers/blob/main/docs/USER_GUIDE.md)`);
