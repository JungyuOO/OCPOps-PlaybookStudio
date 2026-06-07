import { useEffect, useMemo, useRef, useState } from 'react';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import '@xterm/xterm/css/xterm.css';

export type TerminalConnectionState = 'connecting' | 'connected' | 'closed' | 'error';

interface TerminalSocketEvent {
  type?: string;
  data?: string;
  message?: string;
  stage?: string;
  shell?: string;
  workdir?: string;
  cluster_server?: string;
  workspace_namespace?: string;
  sandbox_pod?: string;
  exit_code?: number;
  lab_task_id?: string;
  command_check_id?: string;
  status?: string;
  matched?: boolean;
  validation_result?: Record<string, unknown>;
}

export interface TerminalLearningContext {
  learnerId?: string;
  learningPathId?: string;
  learningStepId?: string;
  labTaskId?: string;
}

interface TerminalSessionPanelProps {
  learningContext?: TerminalLearningContext;
  onCommandCheckResult?: (event: TerminalSocketEvent) => void;
  onCommandSubmitted?: (command: string) => void;
  onOutputChunk?: (chunk: string) => void;
  onSessionStateChange?: (state: TerminalConnectionState) => void;
  onWorkspaceReady?: (workspace: { namespace: string; podName: string }) => void;
}

function defaultTerminalWebSocketUrl(): string {
  const configured = String(import.meta.env.VITE_TERMINAL_WS_URL ?? '').trim();
  if (configured) {
    return configured;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host || '127.0.0.1';
  return `${protocol}//${host}/terminal-ws/`;
}

export default function TerminalSessionPanel({
  learningContext,
  onCommandCheckResult,
  onCommandSubmitted,
  onOutputChunk,
  onSessionStateChange,
  onWorkspaceReady,
}: TerminalSessionPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const commandBufferRef = useRef('');
  const [connectionKey, setConnectionKey] = useState(0);
  const [state, setState] = useState<TerminalConnectionState>('connecting');
  const [recentCheckResults, setRecentCheckResults] = useState<TerminalSocketEvent[]>([]);
  const wsUrl = useMemo(defaultTerminalWebSocketUrl, []);
  const stableLearningContext = useMemo<TerminalLearningContext | undefined>(() => {
    if (!learningContext) {
      return undefined;
    }
    const normalized = {
      learnerId: learningContext.learnerId?.trim(),
      learningPathId: learningContext.learningPathId?.trim(),
      learningStepId: learningContext.learningStepId?.trim(),
      labTaskId: learningContext.labTaskId?.trim(),
    };
    return Object.values(normalized).some(Boolean) ? normalized : undefined;
  }, [
    learningContext?.labTaskId,
    learningContext?.learnerId,
    learningContext?.learningPathId,
    learningContext?.learningStepId,
  ]);

  useEffect(() => {
    onSessionStateChange?.(state);
  }, [onSessionStateChange, state]);

  useEffect(() => {
    const host = containerRef.current;
    if (!host) {
      return undefined;
    }

    setState('connecting');
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

    const scrollTerminalToBottom = (): void => {
      try {
        terminal.scrollToBottom();
      } catch {
        // xterm can reject scroll calls while the viewport is being mounted.
      }
      window.requestAnimationFrame(() => {
        try {
          terminal.scrollToBottom();
        } catch {
          // Ignore transient layout races during panel resize/reconnect.
        }
      });
    };
    scrollTerminalToBottom();

    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    const sendTerminalResize = (): void => {
      if (socket.readyState !== WebSocket.OPEN) {
        return;
      }
      socket.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }));
    };

    const fitTerminal = (): void => {
      try {
        fitAddon.fit();
        sendTerminalResize();
      } catch {
        // The fit addon throws when the panel is still measuring at zero size.
      }
    };
    window.requestAnimationFrame(fitTerminal);
    const resizeObserver = new ResizeObserver(fitTerminal);
    resizeObserver.observe(host);
    const resizeDisposable = terminal.onResize(sendTerminalResize);

    const inputDisposable = terminal.onData((data) => {
      if (data === '\r') {
        const command = commandBufferRef.current.trim();
        commandBufferRef.current = '';
        if (command) {
          onCommandSubmitted?.(command);
        }
      } else if (data === '\u007f') {
        commandBufferRef.current = commandBufferRef.current.slice(0, -1);
      } else if (!data.startsWith('\u001b')) {
        commandBufferRef.current += data;
      }
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }));
      }
      scrollTerminalToBottom();
    });

    const sendTerminalInput = (data: string): void => {
      if (!data) {
        return;
      }
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'input', data }));
      }
      scrollTerminalToBottom();
    };

    const appendCommandBuffer = (data: string): void => {
      for (const char of data) {
        if (char === '\r' || char === '\n') {
          const command = commandBufferRef.current.trim();
          commandBufferRef.current = '';
          if (command) {
            onCommandSubmitted?.(command);
          }
        } else if (char === '\u007f' || char === '\b') {
          commandBufferRef.current = commandBufferRef.current.slice(0, -1);
        } else if (!char.startsWith('\u001b')) {
          commandBufferRef.current += char;
        }
      }
    };

    const pasteHandler = (event: ClipboardEvent): void => {
      if (event.defaultPrevented) {
        return;
      }
      const text = event.clipboardData?.getData('text/plain') ?? '';
      if (!text) {
        return;
      }
      event.preventDefault();
      terminal.focus();
      appendCommandBuffer(text);
      sendTerminalInput(text);
    };
    host.addEventListener('paste', pasteHandler);

    const keydownHandler = (event: KeyboardEvent): void => {
      if (event.defaultPrevented || event.key.toLowerCase() !== 'v' || (!event.ctrlKey && !event.metaKey)) {
        return;
      }
      const clipboard = navigator.clipboard;
      if (!clipboard?.readText) {
        return;
      }
      event.preventDefault();
      void clipboard.readText().then((text) => {
        if (!text) {
          return;
        }
        terminal.focus();
        appendCommandBuffer(text);
        sendTerminalInput(text);
      }).catch(() => {
        // Browser clipboard permission can be denied; native paste remains as a fallback.
      });
    };
    host.addEventListener('keydown', keydownHandler);
    terminal.attachCustomKeyEventHandler((event) => {
      if (event.type !== 'keydown' || event.key.toLowerCase() !== 'v' || (!event.ctrlKey && !event.metaKey)) {
        return true;
      }
      const clipboard = navigator.clipboard;
      if (!clipboard?.readText) {
        return true;
      }
      event.preventDefault();
      void clipboard.readText().then((text) => {
        if (!text) {
          return;
        }
        terminal.focus();
        appendCommandBuffer(text);
        sendTerminalInput(text);
      }).catch(() => {
        // Let xterm/browser defaults handle environments without clipboard permission.
      });
      return false;
    });

    socket.addEventListener('open', () => {
      fitTerminal();
      if (stableLearningContext) {
        socket.send(JSON.stringify({ type: 'context', ...stableLearningContext }));
      }
    });

    socket.addEventListener('message', (event) => {
      let payload: TerminalSocketEvent;
      try {
        payload = JSON.parse(String(event.data)) as TerminalSocketEvent;
      } catch {
        const chunk = String(event.data);
        terminal.write(chunk);
        onOutputChunk?.(chunk);
        scrollTerminalToBottom();
        return;
      }
      if (payload.type === 'bootstrap_stage') {
        const message = payload.message || payload.stage || 'Preparing terminal session.';
        terminal.writeln(message);
        scrollTerminalToBottom();
        return;
      }
      if (payload.type === 'ready') {
        if (payload.workspace_namespace) {
          onWorkspaceReady?.({
            namespace: payload.workspace_namespace,
            podName: payload.sandbox_pod ?? '',
          });
        }
        setState('connected');
        terminal.writeln(`Connected: ${payload.shell ?? 'shell'}`);
        scrollTerminalToBottom();
        return;
      }
      if (payload.type === 'output') {
        const chunk = payload.data ?? '';
        terminal.write(chunk);
        onOutputChunk?.(chunk);
        scrollTerminalToBottom();
        return;
      }
      if (payload.type === 'command_check_result') {
        setRecentCheckResults((current) => [payload, ...current.filter((item) => item.command_check_id !== payload.command_check_id)].slice(0, 4));
        onCommandCheckResult?.(payload);
        return;
      }
      if (payload.type === 'exit') {
        terminal.writeln('');
        terminal.writeln(`Session exited (${payload.exit_code ?? 0}).`);
        setState('closed');
        scrollTerminalToBottom();
        return;
      }
      if (payload.type === 'error') {
        terminal.writeln('');
        terminal.writeln(payload.data ?? 'Terminal session error.');
        setState('error');
        scrollTerminalToBottom();
      }
    });

    socket.addEventListener('close', () => {
      setState((current) => (current === 'closed' ? current : 'closed'));
    });

    socket.addEventListener('error', () => {
      terminal.writeln('');
      terminal.writeln(`Unable to connect to ${wsUrl}`);
      setState('error');
      scrollTerminalToBottom();
    });

    return () => {
      inputDisposable.dispose();
      resizeDisposable.dispose();
      host.removeEventListener('paste', pasteHandler);
      host.removeEventListener('keydown', keydownHandler);
      resizeObserver.disconnect();
      socket.close();
      terminal.dispose();
      socketRef.current = null;
      terminalRef.current = null;
      fitAddonRef.current = null;
    };
  }, [connectionKey, onCommandCheckResult, onCommandSubmitted, onOutputChunk, onWorkspaceReady, stableLearningContext, wsUrl]);

  return (
    <section className="terminal-session-shell" aria-label="Terminal Session">
      <div className="terminal-session-status terminal-session-status--compact">
        <button
          className="terminal-session-reconnect"
          type="button"
          title={state === 'connected' ? 'Reconnect terminal' : 'Connect terminal'}
          onClick={() => setConnectionKey((current) => current + 1)}
        >
          Reconnect
        </button>
      </div>
      {recentCheckResults.length > 0 ? (
        <div className="terminal-session-checks" aria-label="Command check results">
          {recentCheckResults.map((result) => (
            <span
              key={result.command_check_id || `${result.lab_task_id}-${result.status}`}
              className={`terminal-session-check terminal-session-check--${result.status || 'unknown'}`}
            >
              {result.status || 'unknown'}
            </span>
          ))}
        </div>
      ) : null}
      <div ref={containerRef} className="terminal-session-host" />
    </section>
  );
}
