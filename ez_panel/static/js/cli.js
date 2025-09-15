const term = new Terminal({
    cols: 80, // Set the number of columns
    rows: 24, // Set the number of rows
    scrollback: 1000, // Increase the scrollback buffer size
    cursorBlink: true, // Enable cursor blinking for better visibility
});
term.open(document.getElementById("terminal"));
term.write('Welcome to EZ-Panel\r\n$ ');

let command = '';
let history = [];
let historyIndex = 0;

term.onKey(e => {
    const { key, domEvent } = e;

    if (domEvent.key === 'Enter') {
        term.write('\r\n');
        if (command.trim() !== '') {
            fetch('/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command })
            })
            .then(res => res.json())
            .then(data => {
                const lines = data.output.split('\n');
                let index = 0;

                // Throttle the output to prevent overwhelming the terminal
                function writeNextLine() {
                    if (index < lines.length) {
                        term.write(lines[index].trim() + '\r\n');
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
        command += key;
        term.write(key);
    }
});