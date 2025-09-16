# EZ‑Panel

Run it locally or in a container with only the minimal network tooling you need (no full Kali dependency required anymore).

## Network Scanning (Production)

EZ-Panel includes a production-ready network scanner with multiple backends:

- arp-scan (preferred when available): fast L2 ARP sweep with MAC/vendor
- nmap `-sn` host discovery
- concurrent ICMP ping sweep (no MAC/vendor)

Auto subnet discovery on Linux uses `ip -j route` and `ip -j addr`. On other OS or containers without `ip`, it falls back to a `/24` heuristic.

Recommended packages on the host/container:

- `iproute2` (for `ip` command)
- `arp-scan`
- `nmap`

On Debian/Ubuntu:

```bash
apt-get update && apt-get install -y iproute2 arp-scan nmap
```

Container/networking notes:

- For ARP scans inside Docker, run with host networking or grant `NET_ADMIN` and ensure the interface is visible.
- Example `docker run` flags: `--network host --cap-add NET_ADMIN`.
- In `docker-compose.yml`, consider `network_mode: host` for the service that runs EZ-Panel when scanning is required.

API usage:

- `GET /api/devices` — auto-discover and auto-select backend.
- Optional query params:
	- `subnet=192.168.1.0/24`
	- `method=auto|arp-scan|nmap|ping`
	- `include_offline=true` (only impacts ping sweep)
	- `deep=true` (enables SSDP, mDNS, and DHCP lease enrichment)

UI usage:

- On the Dashboard, use the Scan controls to specify CIDR and backend, or leave as auto.

CLI (dev):

```bash
python -m ez_panel.utils.network_scan --cidr 192.168.1.0/24 --method auto
```

### Background scan jobs and history
### Multi-subnet discovery

- List detected local interface subnets:
	```
	GET /api/subnets
	```
- Scan all discovered subnets in one call:
	```
	GET /api/devices?subnet=all
	```
	(Internally aggregates each subnet and de-duplicates by IP.)


- Start a scan: `POST /api/scan/start` with JSON body:
	```json
	{ "subnet": "192.168.1.0/24", "method": "auto", "include_offline": false, "deep": true }
	```
- Poll status: `GET /api/scan/status?job_id=<id>`
- View recent history: `GET /api/scan/history?limit=10`

Scan history is stored in `data/scan_history.jsonl` (path can be changed with `EZ_PANEL_DATA_DIR`).

### Optional enhancements

- OUI vendor mapping: packaged `oui_prefixes.json` used to fill vendor from MAC OUI.
- SSDP/UPnP discovery: M-SEARCH to locate devices/services on the LAN.
- mDNS/Bonjour discovery: if `zeroconf` is installed, discovers common services (e.g. `_http._tcp`).
- DHCP leases parsing: reads `dnsmasq` / `dhcpd` leases when readable to enrich hostnames and MACs.

Install mDNS support:

```bash
pip install zeroconf
```

## Local development with venv (recommended)

Quick bootstrap:

```bash
cd c2_proto
bash scripts/dev-venv.sh
# activate
source .venv/bin/activate
```

Run (safe mode defaults):

```bash
EZ_PANEL_SAFE_MODE=1 EZ_PANEL_SCAN_METHOD_DEFAULT=ping EZ_PANEL_DEEP_DEFAULT=0 EZ_PANEL_INCLUDE_OFFLINE_DEFAULT=0 EZ_PANEL_UI_AUTO_REFRESH_MS=8000 \
EZ-Panel --host 0.0.0.0 --port 5000
```

Makefile shortcuts:

```bash
make venv            # create .venv and install package (editable)
make venv-run-safe   # run app in safe mode on 0.0.0.0:5000
make venv-run        # run app without safe mode envs
```

Production remains available via Docker and systemd as described above.

## Execution & Security Model

The panel is no longer a general-purpose distro shell. It exposes only:

- Network scanning APIs (`/api/devices`, job endpoints)
- An optional command interface restricted by an allowlist
- An optional WebSocket PTY for interactive diagnostics (disabled by default)

### Command Allowlist

Enabled by setting one of:
```
ALLOW_HOST_EXEC=1   # allowlisted host commands
ALLOW_DOCKER_EXEC=1 # (still supported) run inside container specified by EXEC_CONTAINER_NAME
```

Allowlisted base commands (no pipes/redirects/subshells):
```
ls pwd whoami id cat head tail echo arp ip ping traceroute nmap arp-scan netstat ss route hostname uname df free
```
Extend with:
```
EZ_PANEL_EXTRA_CMDS="dig,nslookup"
```
Blocked operators: `;` `&&` `||` `|` `>` `<` backticks and `$(`.

### WebSocket PTY (Experimental)

Provides an interactive shell session with real-time output.

Enable:
```
ALLOW_HOST_EXEC=1 EZ_PANEL_ENABLE_PTY=1 EZ-Panel
```
Connects automatically from the dashboard; falls back to HTTP command mode if not available.

Resize events are forwarded; you can extend the client to send ctrl keys etc. (Current implementation streams raw bytes; special key mapping minimal.)

Security considerations:
- PTY grants a full shell (within host permissions). Combine with containerization.
- Use only on trusted networks or behind authentication (not yet implemented).
- Prefer running behind a reverse proxy with TLS.

### TLS

Direct HTTPS:
```
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -subj "/CN=localhost" -days 365
EZ_PANEL_TLS_CERT=cert.pem EZ_PANEL_TLS_KEY=key.pem EZ-Panel
```

Reverse proxy (nginx) TLS sample is included in `reverse-proxy/nginx.conf` (commented 443 block). Uncomment and mount certs.

## Run locally (Python venv)

Requirements: Python 3.11+ and pip.

```
cd c2_proto
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -U pip
pip install -e .
python -m ez_panel.app
```

Then open http://localhost:5000

## Production

Option A: Compose (recommended for a single host)

```
docker compose -f docker-compose.prod.yml up --build -d
```

Option B: Build/run manually

```
docker build -f Dockerfile.prod -t ezpanel:prod .
docker run -d --name ezpanel -p 5000:5000 ezpanel:prod
```

Gunicorn environment knobs:

- GUNICORN_WORKERS (default: 2*CPU+1)
- GUNICORN_THREADS (default: 2)
- GUNICORN_TIMEOUT (default: 60)
- GUNICORN_LOGLEVEL (default: info)

App options via env:

- `ALLOW_HOST_EXEC=1` allowlist command execution on host
- `ALLOW_DOCKER_EXEC=1` allowlist command execution in target container
- `EZ_PANEL_ENABLE_PTY=1` enable WebSocket PTY (requires `ALLOW_HOST_EXEC=1`)
- `EZ_PANEL_EXTRA_CMDS="cmd1,cmd2"` add extra allowlisted commands
- `EXEC_CONTAINER_NAME=c2panel_c2panel_1` (for docker mode)
- `EXEC_TIMEOUT=30` seconds timeout per command
- `EZ_PANEL_TLS_CERT` / `EZ_PANEL_TLS_KEY` enable direct HTTPS

Health check: GET /healthz (JSON {"ok": true})

### Reverse proxy (optional)

Place a proxy (nginx, Caddy, Traefik) in front to terminate TLS and handle headers. Example nginx compose is provided in `docker-compose.reverse-proxy.yml` with config at `reverse-proxy/nginx.conf`.

## Project layout

- `ez_panel/` — Python package and app entrypoint (`app.py`)
- `.devcontainer/` — Kali-based dev container for Codespaces
- `pyproject.toml` — Package metadata and dependencies
- `.gitignore` — Keeps venv and artifacts out of version control

## Troubleshooting

- Flask not found in editor: This clears after the dev container finishes its postCreate install.
- Port not opening: Check the Ports panel for 5000, or run manually: `source .venv/bin/activate && python -m ez_panel.app`.
- Virtualenv missing: Recreate with `python -m venv .venv` and reinstall with `pip install -e .`.
- WebSocket PTY not connecting: ensure `simple-websocket` installed (pyproject dependency) and `EZ_PANEL_ENABLE_PTY=1 ALLOW_HOST_EXEC=1` set at launch.
- Command rejected: verify base command is in allowlist and no disallowed operators are present.

