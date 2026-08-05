"use strict";
/**
 * WebSocket-based live log stream hook.
 * Requirements: 1.1, 1.2, 1.3
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.useLogStream = useLogStream;
const react_1 = require("react");
const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
function useLogStream({ wsUrl, maxEntries = 500 }) {
    const [logs, setLogs] = (0, react_1.useState)([]);
    const [connectionState, setConnectionState] = (0, react_1.useState)('disconnected');
    const wsRef = (0, react_1.useRef)(null);
    const backoffRef = (0, react_1.useRef)(INITIAL_BACKOFF_MS);
    const timerRef = (0, react_1.useRef)(null);
    const unmountedRef = (0, react_1.useRef)(false);
    const connect = (0, react_1.useCallback)(() => {
        if (unmountedRef.current)
            return;
        setConnectionState('reconnecting');
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;
        ws.onopen = () => {
            if (unmountedRef.current) {
                ws.close();
                return;
            }
            backoffRef.current = INITIAL_BACKOFF_MS;
            setConnectionState('connected');
        };
        ws.onmessage = (event) => {
            if (unmountedRef.current)
                return;
            try {
                const record = JSON.parse(event.data);
                setLogs((prev) => [record, ...prev].slice(0, maxEntries));
            }
            catch {
                // ignore malformed messages
            }
        };
        ws.onclose = () => {
            if (unmountedRef.current)
                return;
            setConnectionState('disconnected');
            const delay = backoffRef.current;
            backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS);
            timerRef.current = setTimeout(connect, delay);
        };
        ws.onerror = () => {
            ws.close();
        };
    }, [wsUrl, maxEntries]);
    (0, react_1.useEffect)(() => {
        unmountedRef.current = false;
        connect();
        return () => {
            unmountedRef.current = true;
            if (timerRef.current)
                clearTimeout(timerRef.current);
            wsRef.current?.close();
        };
    }, [connect]);
    return { logs, connectionState };
}
//# sourceMappingURL=useLogStream.js.map