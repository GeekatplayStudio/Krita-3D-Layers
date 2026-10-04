/**
 * Interactive turntable preview of a library model (port of ImageExpress Asset3DPreview):
 * orbit/zoom with the mouse, slow auto-rotate, city environment, model normalised to fit.
 */
import { Suspense, useEffect, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { ContactShadows, Environment, OrbitControls } from "@react-three/drei";
import { ModelViewer } from "../editor/scene";
import { ModelErrorBoundary } from "./ErrorBoundary";
import { useEnvironmentUrl } from "../three/environments";
import { modelUrl } from "../three/modelSource";

export function ModelPreview({ baseUrl, file, className = "" }: { baseUrl: string | null; file: string; className?: string }) {
    const [url, setUrl] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const env = useEnvironmentUrl("city");

    useEffect(() => {
        let live = true;
        setUrl(null);
        setError(null);
        modelUrl(baseUrl, file)
            .then((u) => live && setUrl(u))
            .catch((e: Error) => live && setError(e.message));
        return () => {
            live = false;
        };
    }, [baseUrl, file]);

    return (
        <div className={`relative checkerboard rounded overflow-hidden ${className}`}>
            {error ? (
                <div className="absolute inset-0 flex items-center justify-center text-[11px] text-muted-foreground p-3 text-center">{error}</div>
            ) : (
                url && (
                    <ModelErrorBoundary key={url} onError={(e) => setError(e.message)} fallback={null}>
                        <Canvas camera={{ position: [1.8, 1.1, 2.4], fov: 40 }} gl={{ alpha: true, antialias: true }} dpr={[1, 2]}>
                            <ambientLight intensity={0.35} />
                            <directionalLight position={[5, 5, 5]} intensity={1.2} />
                            <Suspense fallback={null}>
                                <ModelViewer url={url} />
                                <ContactShadows position={[0, -1, 0]} scale={4} blur={2.5} opacity={0.5} far={2} />
                            </Suspense>
                            {env && <Environment files={env} />}
                            <OrbitControls autoRotate autoRotateSpeed={2.4} enablePan={false} minDistance={1.5} maxDistance={8} makeDefault />
                        </Canvas>
                    </ModelErrorBoundary>
                )
            )}
            {!url && !error && <div className="absolute inset-0 flex items-center justify-center text-[11px] text-muted-foreground">Loading…</div>}
        </div>
    );
}
