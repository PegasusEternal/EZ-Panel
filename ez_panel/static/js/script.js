const cliInput = document.getElementById("cli-input");
const cliRun = document.getElementById("cli-run");
const cliOutput = document.getElementById("cli-output");
const logList = document.getElementById("log-list");

// === CLI run button (connects to Flask backend) ===
cliRun.addEventListener("click", async () => {
    const cmd = cliInput.value.trim();
    if(!cmd) return;

    try {
        const response = await fetch("/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command: cmd })
        });

        const data = await response.json();
        const result = data.output || "";

        // Append CLI output
        cliOutput.innerHTML += `<div>> ${cmd}</div><div>${result}</div>`;
        cliOutput.scrollTop = cliOutput.scrollHeight;

        // Add to activity log
        const logEntry = document.createElement("li");
        logEntry.textContent = `Executed: ${cmd}`;
        logList.appendChild(logEntry);

    } catch(err) {
        cliOutput.innerHTML += `<div>Error executing command: ${err}</div>`;
    }

    cliInput.value = "";
});

// Enter key support
cliInput.addEventListener("keyup", (e) => {
    if(e.key === "Enter") cliRun.click();
});

// === NETWORK DEVICES DYNAMIC TABLE ===
async function updateDevices() {
    try {
        const response = await fetch("/api/devices");
        const devices = await response.json();

        const tableBody = document.getElementById("devices-table-body");
        tableBody.innerHTML = ""; // clear old entries

        if (devices.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="4">No devices detected yet</td></tr>`;
            return;
        }

        devices.forEach(device => {
    const row = document.createElement("tr");

    // Device Name
    const nameCell = document.createElement("td");
    nameCell.textContent = device.name || "Unknown Device";
    row.appendChild(nameCell);

    // Status (online/offline) with class for coloring
    const statusCell = document.createElement("td");
    statusCell.textContent = device.status;
    statusCell.className = device.status.toLowerCase(); // will apply .online or .offline CSS
    row.appendChild(statusCell);

    // IP
    const ipCell = document.createElement("td");
    ipCell.textContent = device.ip;
    row.appendChild(ipCell);

    // Type
    const typeCell = document.createElement("td");
    typeCell.textContent = device.type || "Unknown";
    row.appendChild(typeCell);

    tableBody.appendChild(row);
});

    } catch(err) {
        console.error("Error fetching devices:", err);
    }
}

// === MATRIX ANIMATION ===
const canvas = document.getElementById("matrix-canvas");
const ctx = canvas.getContext("2d");

// Resize canvas to fit the window
function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
}
resizeCanvas();
window.addEventListener("resize", resizeCanvas);

// Matrix animation logic
const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
const fontSize = 16;
const columns = Math.floor(canvas.width / fontSize);
const drops = Array(columns).fill(1);

function drawMatrix() {
    // Clear the canvas with a translucent black rectangle
    ctx.fillStyle = "rgba(0, 0, 0, 0.05)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Set the text style
    ctx.fillStyle = "#0F0"; // Green color
    ctx.font = `${fontSize}px monospace`;

    // Draw the falling letters
    for (let i = 0; i < drops.length; i++) {
        const text = letters.charAt(Math.floor(Math.random() * letters.length));
        ctx.fillText(text, i * fontSize, drops[i] * fontSize);

        // Reset drop to the top randomly or continue falling
        if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) {
            drops[i] = 0;
        }
        drops[i]++;
    }
}

// Start the animation
setInterval(drawMatrix, 50);

// === NETWORK DEVICES DYNAMIC TABLE ===
async function updateDevices() {
    try {
        const response = await fetch("/api/devices");
        const { devices } = await response.json();

        const tableBody = document.getElementById("devices-table-body");
        tableBody.innerHTML = ""; // Clear old entries

        if (!devices || devices.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="4">No devices detected</td></tr>`;
            return;
        }

        devices.forEach(device => {
            const row = document.createElement("tr");

            row.innerHTML = `
                <td>${device.name || "Unknown Device"}</td>
                <td class="${device.status.toLowerCase()}">${device.status}</td>
                <td>${device.ip}</td>
                <td>${device.type || "Unknown"}</td>
            `;

            tableBody.appendChild(row);
        });
    } catch (err) {
        console.error("Error fetching devices:", err);
    }
}

// Initial load and periodic refresh
updateDevices();
setInterval(updateDevices, 5000);