/**
 * Contains a 3D model load failure so it cannot take the page down (from ImageExpress
 * ModelErrorBoundary): useGLTF throws on a failed load, and without a boundary the whole
 * React tree would unmount. A model that will not load deserves a message, not a crash.
 */
import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; fallback?: ReactNode; onError?: (error: Error) => void };

export class ModelErrorBoundary extends Component<Props, { error: Error | null }> {
    override state: { error: Error | null } = { error: null };

    static getDerivedStateFromError(error: Error) {
        return { error };
    }

    override componentDidCatch(error: Error) {
        console.error("3D model failed to load:", error);
        this.props.onError?.(error);
    }

    override render() {
        if (this.state.error) return this.props.fallback ?? null;
        return this.props.children;
    }
}
