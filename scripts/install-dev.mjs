// Copies the plugin into Krita's pykrita folder and enables it, for development.
//   npm run install:krita        (then restart Krita)
//   node scripts/install-dev.mjs --remove
// End users use the installer in install/ or Krita's "Import Python Plugin from File".
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const resources =
    process.platform === "win32" ? join(process.env.APPDATA, "krita") : process.platform === "darwin" ? join(homedir(), "Library/Application Support/krita") : join(process.env.XDG_DATA_HOME ?? join(homedir(), ".local/share"), "krita");
const kritarc = process.platform === "win32" ? join(process.env.LOCALAPPDATA, "kritarc") : process.platform === "darwin" ? join(homedir(), "Library/Preferences/kritarc") : join(process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config"), "kritarc");
const pykrita = join(resources, "pykrita");
const target = join(pykrita, "geekatplay_3d_layers");
const desktop = join(pykrita, "geekatplay_3d_layers.desktop");

rmSync(target, { recursive: true, force: true });
rmSync(desktop, { force: true });
if (process.argv.includes("--remove")) {
    console.log(`Removed the plugin from ${pykrita}`);
    process.exit(0);
}
mkdirSync(pykrita, { recursive: true });
cpSync(join(root, "plugin/geekatplay_3d_layers"), target, { recursive: true, filter: (src) => !src.includes("__pycache__") });
cpSync(join(root, "plugin/geekatplay_3d_layers.desktop"), desktop);

// Enable it: Krita keeps the plugin switches in kritarc, section [python].
let rc = existsSync(kritarc) ? readFileSync(kritarc, "utf8") : "";
if (!/^enable_geekatplay_3d_layers=true$/m.test(rc)) {
    rc = rc.replace(/^enable_geekatplay_3d_layers=.*\r?\n?/m, "");
    rc = /^\[python\]$/m.test(rc) ? rc.replace(/^\[python\]\r?\n/m, (m) => `${m}enable_geekatplay_3d_layers=true\n`) : `${rc.trimEnd()}\n\n[python]\nenable_geekatplay_3d_layers=true\n`;
    writeFileSync(kritarc, rc);
}
console.log(`Installed into ${target} and enabled it in ${kritarc}. Restart Krita (close it first, or it rewrites kritarc).`);
