// cli.js - Terminal panel logic for EZ-Panel
//
// Responsibilities:
// - Initialize xterm.js terminal and dynamically fit it to container size
// - Prefer WebSocket PTY backend (/ws/pty) when enabled; fallback to /run HTTP API
// - Handle basic line editing, command history, and throttled output rendering
// - Notify PTY of size changes to maintain correct wrapping

// Initialize terminal WITHOUT fixed cols/rows so we can dynamically fit container
const term = new Terminal({
    scrollback: 5000,
    cursorBlink: true,
    convertEol: true,
    disableStdin: false,
});
let useWebSocket = false;
let ws = null;
let ptyReady = false;
function initWebSocket() {
    try {
        const proto = (window.location.protocol === 'https:') ? 'wss' : 'ws';
        ws = new WebSocket(`${proto}://${window.location.host}/ws/pty`);
        ws.onopen = () => { useWebSocket = true; ptyReady = true; term.write('[PTY mode]\r\n$ '); sendResize(); };
        ws.onmessage = (ev) => { term.write(ev.data.replace(/\n/g, '\r\n')); };
        ws.onclose = () => { useWebSocket = false; ptyReady = false; term.write('\r\n[PTY disconnected: fallback]\r\n$ '); };
        ws.onerror = () => { /* fallback silently */ };
    } catch (e) {
        // Ignore - we fallback to HTTP command mode
    }
}
initWebSocket();

function sendResize() {
    if (!useWebSocket || !ws || ws.readyState !== WebSocket.OPEN) return;
    const cols = term.cols || 80;
    const rows = term.rows || 24;
    ws.send(`__RESIZE__ ${cols} ${rows}`);
}

// Re-issue resize after fit operations
const _oldFit = fitTerminal;
function fitTerminalWrapper() { _oldFit(); sendResize(); }
// Replace reference used below
fitTerminal = fitTerminalWrapper;

const terminalContainer = document.getElementById("terminal");
term.open(terminalContainer);

function computeCellSize() {
    // Try to read actual cell metrics from xterm internals or DOM
    let cellWidth = 9, cellHeight = 18; // sensible defaults for 14px monospace
    try {
        if (term._core?._renderService?.dimensions) { // internal API (best effort)
            const dims = term._core._renderService.dimensions;
            if (dims.actualCellWidth) cellWidth = dims.actualCellWidth;
            if (dims.actualCellHeight) cellHeight = dims.actualCellHeight;
        } else {
            const row = terminalContainer.querySelector('.xterm-rows > div');
            if (row) {
                const rStyles = window.getComputedStyle(row);
                cellHeight = parseFloat(rStyles.lineHeight) || cellHeight;
                // Width per char: measure first span if present
                const span = row.querySelector('span');
                if (span && span.textContent) {
                    const spanRect = span.getBoundingClientRect();
                    cellWidth = spanRect.width / span.textContent.length;
                }
            }
        }
    } catch (e) {
        // swallow
    }
    return { cellWidth, cellHeight };
}

function fitTerminal() {
    if (!terminalContainer || !terminalContainer.clientWidth || !terminalContainer.clientHeight) return;
    const { cellWidth, cellHeight } = computeCellSize();
    const paddingX = 8; // account for borders
    const paddingY = 8;
    const availWidth = terminalContainer.clientWidth - paddingX;
    const availHeight = terminalContainer.clientHeight - paddingY;
    let cols = Math.max(20, Math.floor(availWidth / cellWidth));
    let rows = Math.max(8, Math.floor(availHeight / cellHeight));
    try {
        term.resize(cols, rows);
    } catch (e) {
        // ignore resize errors
    }
}

// Debounce helper
let fitTimer = null;
function scheduleFit(delay = 50) {
    if (fitTimer) clearTimeout(fitTimer);
    fitTimer = setTimeout(() => {
        fitTerminal();
        // second pass after render stabilization
        setTimeout(fitTerminal, 60);
    }, delay);
}

// Initial greeting after a short delay to allow sizing
scheduleFit(30);
term.write('Welcome to EZ-Panel (dynamic terminal)\r\n');
term.write('$ ');

window.addEventListener('resize', () => scheduleFit(80));

// Observe size changes (flex layout changes) using ResizeObserver if available
if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => scheduleFit(20));
    ro.observe(terminalContainer);
}

let command = '';
let history = [];
let historyIndex = 0;

term.onKey(e => {
    const { key, domEvent } = e;

    if (domEvent.key === 'Enter') {
        term.write('\r\n');
        if (useWebSocket && ptyReady) {
            // Send command + newline directly to PTY
            ws.send(command + '\n');
            history.push(command);
            historyIndex = history.length;
            command = '';
            return; // output will come asynchronously
        }
        if (command.trim() !== '') {
            fetch('/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command })
            })
            .then(async res => {
                let data = null;
                try {
                    data = await res.json();
                } catch (e) {
                    // Non-JSON response
                    data = null;
                }

                let out = '';
                if (!res.ok) {
                    const errText = (data && (data.error || data.message || data.output)) || res.statusText || 'Request failed';
                    out = `Error (${res.status}): ${errText}`;
                } else {
                    if (data && typeof data.output === 'string') {
                        out = data.output;
                    } else if (data && data.error) {
                        out = `Error: ${data.error}`;
                    } else {
                        out = '';
                    }
                }

                if (!out) {
                    out = 'No output.\r\n(Command execution may be disabled by the server.)';
                }

                const lines = String(out).split('\n');
                let index = 0;

                // Throttle the output to prevent overwhelming the terminal
                function writeNextLine() {
                    if (index < lines.length) {
                        term.write(lines[index].replace(/\r?$/,'') + '\r\n');
                        index++;
                        setTimeout(writeNextLine, 10); // Add a small delay between lines
                    } else {
                        term.scrollToBottom();
                        term.write('$ ');
                    }
                }

                writeNextLine();
            })
            .catch(err => {
                term.write(`Error: ${err.message}\r\n$ `);
                term.scrollToBottom(); // Ensure the terminal scrolls even on error
            });
            history.push(command);
            historyIndex = history.length;
        } else {
            term.write('$ ');
        }
        command = '';
    } else if (domEvent.key === 'Backspace') {
        if (command.length > 0) {
            command = command.slice(0, -1);
            term.write('\b \b');
        }
    } else if (domEvent.key === 'ArrowUp') {
        if (historyIndex > 0) {
            historyIndex--;
            command = history[historyIndex];
            term.write(`\x1b[2K\r$ ${command}`);
        }
    } else if (domEvent.key === 'ArrowDown') {
        if (historyIndex < history.length - 1) {
            historyIndex++;
            command = history[historyIndex];
            term.write(`\x1b[2K\r$ ${command}`);
        } else {
            historyIndex = history.length;
            command = '';
            term.write('\x1b[2K\r$ ');
        }
    } else if (key.length === 1) {
        if (useWebSocket && ptyReady) {
            ws.send(key);
            term.write(key);
        } else {
            command += key;
            term.write(key);
        }
    }
});