import { useEffect, useMemo, useRef, useState } from 'react';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

type TerminalConnectionState = 'connecting' | 'connected' | 'closed' | 'error';

interface TerminalSocketEvent {
  type?: string;
  data?: string;
  shell?: string;
  workdir?: string;
  exit_code?: number;
}

export interface TerminalLearningContext {
  learnerId?: string;
  learningPathId?: string;
  learningStepId?: string;
  labTaskId?: string;
}

interface TerminalSessionPanelProps {
  learningContext?: TerminalLearningContext;
}

function defaultTerminalWebSocketUrl(): string {
  const configured = String(import.meta.env.VITE_TERMINAL_WS_URL ?? '').trim();
  if (configured) {
    return configured;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname || '127.0.0.1';
  return `${protocol}//${host}:8770`;
}

export default function TerminalSessionPanel({ learningContext }: TerminalSessionPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const [connectionKey, setConnectionKey] = useState(0);
  const [state, setState] = useState<TerminalConnectionState>('connecting');
  const [sessionMeta, setSessionMeta] = useState({ shell: '', workdir: '' });
  const wsUrl = useMemo(defaultTerminalWebSocketUrl, []);

  useEffect(() => {
    const host = containerRef.current;
    if (!host) {
      return undefined;
    }

    setState('connecting');
    setSessionMeta({ shell: '', workdir: '' });
    const terminal = new Terminal({
      cursorBlink: true,
      convertEol: true,
      disableStdin: false,
      fontFamily: '"Cascadia Mono", "Fira Code", Consolas, monospace',
      fontSize: 13,
      lineHeight: 1.18,
      scrollback: 5000,
      theme: {
        background: '#070b12',
        foreground: '#dbe8ef',
        cursor: '#58d4ff',
        selectionBackground: '#1f6f8c',
        black: '#0b1017',
        blue: '#58a6ff',
        cyan: '#39d7ff',
        green: '#66d17a',
        magenta: '#c084fc',
        red: '#ff7b72',
        white: '#dbe8ef',
        yellow: '#f2cc60',
      },
    });
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(host);
    terminal.writeln('Connecting to Terminal Session...');
    terminalRef.current = terminal;
    fitAddonRef.current = fitAddon;

    const fitTerminal = (): void => {
      try {
        fitAddon.fit();
      } catch {
        // The fit addon throws when the panel is still measuring at zero size.
      }
    };
    window.requestAnimationFrame(fitTerminal);
    const resizeObserver = new ResizeObserver(fitTerminal);
    resizeObserver.observe(host);

    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    const inputDisposable = terminal.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }));
      }
    });

    socket.addEventListener('open', () => {
      setState('connected');
      if (learningContext) {
        socket.send(JSON.stringify({ type: 'context', ...learningContext }));
      }
    });

    socket.addEventListener('message', (event) => {
      let payload: TerminalSocketEvent;
      try {
        payload = JSON.parse(String(event.data)) as TerminalSocketEvent;
      } catch {
        terminal.write(String(event.data));
        return;
      }
      if (payload.type === 'ready') {
        setSessionMeta({
          shell: payload.shell ?? '',
          workdir: payload.workdir ?? '',
        });
        terminal.writeln(`Connected: ${payload.shell ?? 'shell'}`);
        return;
      }
      if (payload.type === 'output') {
        terminal.write(payload.data ?? '');
        return;
      }
      if (payload.type === 'exit') {
        terminal.writeln('');
        terminal.writeln(`Session exited (${payload.exit_code ?? 0}).`);
        setState('closed');
        return;
      }
      if (payload.type === 'error') {
        terminal.writeln('');
        terminal.writeln(payload.data ?? 'Terminal session error.');
        setState('error');
      }
    });

    socket.addEventListener('close', () => {
      setState((current) => (current === 'closed' ? current : 'closed'));
    });

    socket.addEventListener('error', () => {
      terminal.writeln('');
      terminal.writeln(`Unable to connect to ${wsUrl}`);
      setState('error');
    });

    return () => {
      inputDisposable.dispose();
      resizeObserver.disconnect();
      socket.close();
      terminal.dispose();
      socketRef.current = null;
      terminalRef.current = null;
      fitAddonRef.current = null;
    };
  }, [connectionKey, learningContext, wsUrl]);

  return (
    <section className="terminal-session-shell" aria-label="Terminal Session">
      <div className="terminal-session-status">
        <div className="terminal-session-meta">
          <span className={`terminal-session-dot terminal-session-dot--${state}`} />
          <strong>{state === 'connected' ? 'Connected' : state === 'connecting' ? 'Connecting' : state === 'error' ? 'Connection error' : 'Closed'}</strong>
          {sessionMeta.shell ? <span>{sessionMeta.shell}</span> : null}
          {sessionMeta.workdir ? <span>{sessionMeta.workdir}</span> : null}
        </div>
        <button
          className="terminal-session-reconnect"
          type="button"
          onClick={() => setConnectionKey((current) => current + 1)}
        >
          Reconnect
        </button>
      </div>
      <div ref={containerRef} className="terminal-session-host" />
    </section>
  );
}
