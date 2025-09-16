// script.js - Main dashboard interactions for EZ-Panel
//
// Responsibilities:
// - Wire the minimal CLI textarea/button to the backend /run endpoint
// - Render the network devices table by calling /api/devices
// - Trigger background scans via /api/scan/start and poll status
// - Draw a simple 'matrix' canvas animation for flair
// - Periodically refresh device data according to server-provided settings

const cliInput = document.getElementById("cli-input");
const cliRun = document.getElementById("cli-run");
const cliOutput = document.getElementById("cli-output");
const logList = document.getElementById("log-list");

// === CLI run button (connects to Flask backend) ===
if (cliRun) cliRun.addEventListener("click", async () => {
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
if (cliInput) cliInput.addEventListener("keyup", (e) => {
    if(e.key === "Enter" && cliRun) cliRun.click();
});

// === NETWORK DEVICES DYNAMIC TABLE ===
async function updateDevices(params = {}) {
    try {
        const qs = new URLSearchParams(params).toString();
        const response = await fetch(`/api/devices${qs ? `?${qs}` : ""}`);
        const payload = await response.json();
        const devices = payload.devices || payload || [];

        const tableBody = document.getElementById("devices-table-body");
        tableBody.innerHTML = ""; // clear old entries

        if (!devices || devices.length === 0) {
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

    // MAC
    const macCell = document.createElement("td");
    macCell.textContent = device.mac || "";
    row.appendChild(macCell);

    // Vendor
    const vendorCell = document.createElement("td");
    vendorCell.textContent = device.vendor || "";
    row.appendChild(vendorCell);

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
                <td>${device.mac || ""}</td>
                <td>${device.vendor || ""}</td>
            `;

            tableBody.appendChild(row);
        });
    } catch (err) {
        console.error("Error fetching devices:", err);
    }
}

// Wire up scan controls
const scanBtn = document.getElementById("scan-trigger");
const scanSubnet = document.getElementById("scan-subnet");
const scanMethod = document.getElementById("scan-method");
const scanIncludeOffline = document.getElementById("scan-include-offline");
let scanJobId = null;

function setProgress(pct, text = "") {
    let el = document.getElementById("scan-progress");
    if (!el) {
        el = document.createElement("div");
        el.id = "scan-progress";
        el.style.margin = "8px 0";
        el.style.fontFamily = "monospace";
        const panel = document.getElementById("network-panel");
        if (panel) panel.insertBefore(el, panel.querySelector("table"));
    }
    el.textContent = `Scan progress: ${pct}% ${text}`;
}

async function triggerScan() {
    const payload = {
        subnet: (scanSubnet && scanSubnet.value || "").trim() || undefined,
        method: (scanMethod && scanMethod.value) || "auto",
        include_offline: !!(scanIncludeOffline && scanIncludeOffline.checked),
        deep: true
    };
    try {
        const resp = await fetch('/api/scan/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await resp.json();
        scanJobId = data.job_id;
        setProgress(0, '(queued)');
        pollScanStatus();
    } catch (e) {
        console.error('scan start error', e);
    }
}

async function pollScanStatus() {
    if (!scanJobId) return;
    try {
        const resp = await fetch(`/api/scan/status?job_id=${encodeURIComponent(scanJobId)}`);
        const data = await resp.json();
        setProgress(data.progress ?? 0, `(${data.status})`);
        if (data.status === 'completed') {
            await updateDevices();
            setTimeout(() => setProgress(100, '(done)'), 500);
            scanJobId = null;
            return;
        }
        if (data.status === 'failed') {
            setProgress(100, `(failed: ${data.error || 'error'})`);
            scanJobId = null;
            return;
        }
        setTimeout(pollScanStatus, 1000);
    } catch (e) {
        console.error('scan status error', e);
        setTimeout(pollScanStatus, 1500);
    }
}

if (scanBtn) scanBtn.addEventListener("click", triggerScan);

// Initial load and periodic refresh (configurable via server_info)
(async function initDevices() {
    let refreshMs = 5000;
    try {
        const r = await fetch('/api/server_info');
        const info = await r.json();
        if (info && info.config) {
            refreshMs = info.config.ui_auto_refresh_ms || 5000;
            const safe = !!info.config.safe_mode;
            if (safe) {
                // In safe mode, we avoid deep scans by default and let backend enforce safe defaults
                if (scanMethod) scanMethod.value = 'ping';
                if (scanIncludeOffline) scanIncludeOffline.checked = false;
            }
        }
    } catch (e) { /* ignore */ }
    updateDevices();
    setInterval(updateDevices, refreshMs);
})();