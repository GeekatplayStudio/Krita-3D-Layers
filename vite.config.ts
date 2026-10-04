import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

const root = fileURLToPath(new URL(".", import.meta.url));

/** Ships three.js' Draco and Basis decoders (web/draco, web/basis) so compressed GLBs open offline. */
function decoders(): Plugin {
    const dirs = {
        draco: resolve(root, "node_modules/three/examples/jsm/libs/draco/gltf"),
        basis: resolve(root, "node_modules/three/examples/jsm/libs/basis"),
    };
    return {
        name: "g3d-decoders",
        configureServer(server) {
            server.middlewares.use((req, res, next) => {
                const m = /^\/(draco|basis)\/([\w.]+)$/.exec(req.url?.split("?")[0] ?? "");
                if (!m) return next();
                try {
                    const body = readFileSync(resolve(dirs[m[1] as keyof typeof dirs], m[2]));
                    res.setHeader("Content-Type", m[2].endsWith(".wasm") ? "application/wasm" : "text/javascript");
                    res.end(body);
                } catch {
                    next();
                }
            });
        },
        generateBundle() {
            for (const [name, dir] of Object.entries(dirs)) {
                for (const file of readdirSync(dir).filter((f) => /\.(js|wasm)$/.test(f))) {
                    this.emitFile({ type: "asset", fileName: `${name}/${file}`, source: readFileSync(resolve(dir, file)) });
                }
            }
        },
    };
}

/*
 * The 3D editor and the task page, served to a browser window by the plugin's local
 * server (plugin/geekatplay_3d_layers/ui/server.py), so asset paths stay relative ("./").
 * `npm run dev` serves the same pages against the mock host with the samples in
 * tests/fixtures/public, which are never part of the plugin.
 */
export default defineConfig(({ command }) => ({
    root: resolve(root, "web/src/web"),
    base: "./",
    publicDir: command === "serve" ? resolve(root, "tests/fixtures/public") : false,
    plugins: [react(), tailwindcss(), decoders()],
    optimizeDeps: {
        include: ["FBXLoader", "OBJLoader", "MTLLoader", "STLLoader", "PLYLoader", "ColladaLoader", "3MFLoader", "AMFLoader", "TDSLoader", "VRMLLoader", "USDLoader", "VOXLoader", "TGALoader"]
            .map((l) => `three/examples/jsm/loaders/${l}.js`)
            .concat("three/examples/jsm/exporters/GLTFExporter.js"),
    },
    resolve: {
        alias: {
            "@shared": resolve(root, "web/src/shared"),
            "@web": resolve(root, "web/src/web"),
        },
    },
    build: {
        outDir: resolve(root, "plugin/geekatplay_3d_layers/web"),
        emptyOutDir: true,
        target: "es2022",
        sourcemap: false,
        chunkSizeWarningLimit: 2500,
        rollupOptions: {
            input: {
                editor: resolve(root, "web/src/web/editor.html"),
                tasks: resolve(root, "web/src/web/tasks.html"),
            },
        },
    },
    server: {
        port: 5318,
        strictPort: true,
    },
}));
