export class ReconnectingWebSocket {
  private url: string;
  private ws: WebSocket | null = null;
  private reconnectDelay = 500;
  private maxReconnectDelay = 5000;
  private shouldReconnect = true;
  private messageListeners: ((data: any) => void)[] = [];
  private statusListeners: ((connected: boolean) => void)[] = [];

  constructor(url?: string) {
    const loc = window.location;
    const defaultUrl = (loc.protocol === 'https:' ? 'wss://' : 'ws://') + loc.host + '/ws';
    this.url = url || defaultUrl;
    this.connect();
  }

  private connect() {
    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.reconnectDelay = 500;
        this.notifyStatus(true);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.messageListeners.forEach((fn) => fn(data));
        } catch (err) {
          console.error('[WS] Failed to parse message', err);
        }
      };

      this.ws.onclose = () => {
        this.notifyStatus(false);
        if (this.shouldReconnect) {
          setTimeout(() => {
            this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxReconnectDelay);
            this.connect();
          }, this.reconnectDelay);
        }
      };

      this.ws.onerror = (err) => {
        console.warn('[WS] Socket error', err);
        this.ws?.close();
      };
    } catch (err) {
      this.notifyStatus(false);
      setTimeout(() => this.connect(), this.reconnectDelay);
    }
  }

  public onMessage(fn: (data: any) => void) {
    this.messageListeners.push(fn);
    return () => {
      this.messageListeners = this.messageListeners.filter((l) => l !== fn);
    };
  }

  public onStatus(fn: (connected: boolean) => void) {
    this.statusListeners.push(fn);
    return () => {
      this.statusListeners = this.statusListeners.filter((l) => l !== fn);
    };
  }

  private notifyStatus(connected: boolean) {
    this.statusListeners.forEach((fn) => fn(connected));
  }

  public send(cmd: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(cmd));
    } else {
      console.warn('[WS] Cannot send, socket not open', cmd);
    }
  }

  public close() {
    this.shouldReconnect = false;
    this.ws?.close();
  }
}

export const socket = new ReconnectingWebSocket();
