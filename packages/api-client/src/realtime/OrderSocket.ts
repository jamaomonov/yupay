import type { OrderUpdateMessage } from "./messages";

export interface OrderSocketOptions {
  /** Full `wss://...` URL (no query string needed; the token is supplied separately). */
  url: string;
  /** Returns a short-lived JWT minted from the user's access token. Re-invoked on reconnect. */
  getToken: () => Promise<string>;
  onMessage: (msg: OrderUpdateMessage) => void;
  onOpen?: () => void;
  onClose?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
}

/**
 * Reconnecting WebSocket client for order updates.
 *
 * - Exponential backoff (cap 30s).
 * - Heartbeat every 25 s; closes the socket if no message in 60 s.
 * - Re-fetches a fresh handshake token on every reconnect.
 */
export class OrderSocket {
  private socket: WebSocket | null = null;
  private reconnectAttempt = 0;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private aliveTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(private readonly opts: OrderSocketOptions) {}

  async connect(): Promise<void> {
    if (this.closed) return;
    const token = await this.opts.getToken();
    const sep = this.opts.url.includes("?") ? "&" : "?";
    const url = `${this.opts.url}${sep}token=${encodeURIComponent(token)}`;
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.addEventListener("open", () => {
      this.reconnectAttempt = 0;
      this.startHeartbeat();
      this.resetAlive();
      this.opts.onOpen?.();
    });

    socket.addEventListener("message", (ev) => {
      this.resetAlive();
      try {
        const msg = JSON.parse(ev.data as string) as OrderUpdateMessage;
        this.opts.onMessage(msg);
      } catch {
        // ignore malformed payloads
      }
    });

    socket.addEventListener("error", (ev) => this.opts.onError?.(ev));
    socket.addEventListener("close", (ev) => {
      this.stopHeartbeat();
      this.opts.onClose?.(ev);
      if (!this.closed) this.scheduleReconnect();
    });
  }

  close(): void {
    this.closed = true;
    this.stopHeartbeat();
    this.socket?.close();
  }

  private scheduleReconnect(): void {
    const backoff = Math.min(30_000, 500 * 2 ** this.reconnectAttempt);
    this.reconnectAttempt += 1;
    setTimeout(() => void this.connect(), backoff);
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      this.socket?.send(JSON.stringify({ type: "ping" }));
    }, 25_000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.aliveTimer) clearTimeout(this.aliveTimer);
    this.heartbeatTimer = null;
    this.aliveTimer = null;
  }

  private resetAlive(): void {
    if (this.aliveTimer) clearTimeout(this.aliveTimer);
    this.aliveTimer = setTimeout(() => this.socket?.close(), 60_000);
  }
}
