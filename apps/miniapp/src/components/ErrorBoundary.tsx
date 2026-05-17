/**
 * Top-level error boundary so the miniapp never white-screens on a thrown
 * render error. Wraps the router in App.tsx.
 *
 * Class component because that's still React's only way to catch render
 * errors below the boundary. Functional ErrorBoundary doesn't exist (yet).
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Print to console only; production telemetry is wired through Sentry when
    // we add it at the app level.
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught", error, info);
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  override render(): ReactNode {
    if (this.state.error) {
      return <Fallback message={this.state.error.message} onReset={this.reset} />;
    }
    return this.props.children;
  }
}

function Fallback({ message, onReset }: { message: string; onReset: () => void }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6 text-center space-y-5">
      <div
        className="w-14 h-14 rounded-2xl flex items-center justify-center"
        style={{ background: "hsl(0 70% 50% / 0.18)", color: "hsl(0 80% 70%)" }}
        aria-hidden
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          width="22"
          height="22"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      </div>
      <div className="space-y-1">
        <p className="text-white font-bold text-lg">Что-то сломалось</p>
        <p className="text-white/40 text-xs max-w-xs leading-relaxed">
          {message || "Перезапустите приложение или вернитесь в чат и откройте миниапп заново."}
        </p>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => {
            onReset();
            window.location.assign("/");
          }}
          className="px-5 py-2.5 rounded-2xl text-sm font-bold"
          style={{ background: "hsl(var(--primary))", color: "#000" }}
        >
          На главную
        </button>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="px-5 py-2.5 rounded-2xl text-sm font-semibold text-white/70"
          style={{
            background: "hsl(var(--surface-2))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          Перезагрузить
        </button>
      </div>
    </div>
  );
}
