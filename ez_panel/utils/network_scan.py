"""
Network scanning utilities for EZ-Panel.

What this module does
---------------------
- Discovers local subnets (CIDRs) using Linux `ip` output, with hostname-based fallback.
- Scans networks using (in order of preference):
    1) arp-scan (fast, layer 2)
    2) Nmap -sn (host discovery)
    3) Concurrent ICMP ping (fallback)
- Enriches discovered hosts using ARP neighbor table, DHCP leases, SSDP, and mDNS.
- Normalizes output into a consistent device dictionary.

Device dictionary shape
-----------------------
    {
        "name": str,      # reverse DNS or IP
        "ip": str,        # IPv4
        "status": str,    # 'online' or 'offline'
        "type": str,      # 'unknown', 'ssdp', 'mdns', etc.
        "mac": Optional[str],
        "vendor": Optional[str],
    }

Operational notes
-----------------
- On Docker, L2 scans (arp-scan) generally require host networking or NET_ADMIN.
- Optional dependencies (zeroconf) are used when available and otherwise skipped.

Customization
-------------
- Adjust the scanning method defaults from the server (see create_app() helpers).
- Extend deep_discovery merges or add new enrichment sources following the patterns below.
"""

from __future__ import annotations

import json
import platform
import ipaddress
import socket
import subprocess
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Tuple
import os
import time
import re
import socket as _socket


def _sh(cmd: List[str], timeout: int = 10) -> Tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception as exc:
        return 1, "", str(exc)


def _which(name: str) -> Optional[str]:
    """Return full path of an executable if available in PATH; else None."""
    return shutil.which(name)


def discover_local_cidr() -> Optional[str]:
    """Discover the primary local IPv4 CIDR using Linux `ip` output.

    Falls back to hostname heuristics if needed.
    """
    # Linux: use `ip -j route` to find default route dev, then `ip -j addr` for that dev
    if platform.system().lower() == "linux" and _which("ip"):
        rc, out, _ = _sh(["ip", "-j", "route", "show", "default"])
        if rc == 0 and out.strip():
            try:
                routes = json.loads(out)
                if routes:
                    dev = routes[0].get("dev")
                    if dev:
                        rc2, out2, _ = _sh(["ip", "-j", "addr", "show", "dev", dev])
                        if rc2 == 0 and out2.strip():
                            addrs = json.loads(out2)
                            for a in addrs:
                                for addrinfo in a.get("addr_info", []):
                                    if addrinfo.get("family") == "inet":
                                        local = addrinfo.get("local")
                                        prefix = addrinfo.get("prefixlen")
                                        if local and prefix is not None:
                                            try:
                                                net = ipaddress.ip_network(f"{local}/{prefix}", strict=False)
                                                return str(net)
                                            except Exception:
                                                pass
            except Exception:
                pass

    # Heuristic fallback: use hostname and assume /24
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        if local_ip.startswith("127."):
            return None
        return str(ipaddress.ip_network(local_ip + "/24", strict=False))
    except Exception:
        return None


def discover_all_local_cidrs(max_prefix: int = 30) -> List[str]:
    """Discover all interface IPv4 CIDRs (non-loopback) via `ip -j addr`.

    Filters out very small host networks (/31,/32) and very large (/8) except private ranges.
    """
    cidrs: List[str] = []
    seen: set = set()
    if platform.system().lower() == "linux" and _which("ip"):
        rc, out, _ = _sh(["ip", "-j", "addr"], timeout=10)
        if rc == 0 and out.strip():
            try:
                data = json.loads(out)
                for iface in data:
                    ifname = iface.get("ifname")
                    if not ifname or ifname.startswith("lo"):
                        continue
                    for addrinfo in iface.get("addr_info", []):
                        if addrinfo.get("family") != "inet":
                            continue
                        local = addrinfo.get("local")
                        prefix = addrinfo.get("prefixlen")
                        if not local or prefix is None:
                            continue
                        if local.startswith("127."):
                            continue
                        try:
                            net = ipaddress.ip_network(f"{local}/{prefix}", strict=False)
                        except Exception:
                            continue
                        # Basic filtering: drop extremely small or link-local 169.254/16
                        if str(net).startswith("169.254."):
                            continue
                        if net.prefixlen <= 8 and not (
                            str(net).startswith("10.") or str(net).startswith("172.") or str(net).startswith("192.168.")
                        ):
                            # Avoid giant public nets accidentally
                            continue
                        if net.prefixlen > max_prefix:
                            # Too specific (/31,/32) usually host or point-to-point
                            continue
                        s = str(net)
                        if s not in seen:
                            seen.add(s)
                            cidrs.append(s)
            except Exception:
                pass
    # Fallback to single
    if not cidrs:
        c = discover_local_cidr()
        if c:
            cidrs.append(c)
    return cidrs


# -------------------------
# Wi‑Fi station enumeration (best-effort)
# -------------------------
def _iw_list_interfaces() -> List[Dict[str, str]]:
    """Return list of wifi interfaces with 'ifname' and 'type' using `iw dev`.

    Example 'iw dev' snippet:
        Interface wlan0
            ifindex 3
            wdev 0x1
            addr 00:11:22:33:44:55
            type managed
    or type AP when acting as an access point.
    """
    if not _which("iw"):
        return []
    rc, out, _ = _sh(["iw", "dev"], timeout=5)
    if rc != 0 or not out:
        return []
    ifaces: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Interface "):
            if current:
                ifaces.append(current)
            current = {"ifname": line.split()[1]}
        elif line.startswith("type ") and current:
            current["type"] = line.split()[1]
    if current:
        ifaces.append(current)
    return ifaces


def _iw_station_dump(iface: str) -> List[str]:
    """Return list of station MAC addresses for a given iface using `iw dev IFACE station dump`."""
    if not _which("iw"):
        return []
    rc, out, _ = _sh(["iw", "dev", iface, "station", "dump"], timeout=5)
    if rc != 0 or not out:
        return []
    macs: List[str] = []
    for line in out.splitlines():
        line = line.strip()
        # Lines start with: Station aa:bb:cc:dd:ee:ff (on wlan0)
        if line.lower().startswith("station "):
            parts = line.split()
            if len(parts) >= 2:
                mac = parts[1].strip().lower()
                # basic validation
                if re.match(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$", mac):
                    macs.append(_normalize_mac(mac))
    return macs


def discover_wifi_stations() -> List[Dict[str, Optional[str]]]:
    """Discover associated Wi‑Fi stations (when acting as AP) and map MAC->IP best-effort.

    Returns dicts with: mac, ip, name, status, type='wifi-station'.
    """
    stations: List[Dict[str, Optional[str]]] = []
    ifaces = _iw_list_interfaces()
    if not ifaces:
        return stations
    # Merge helpers
    neighbors = _arp_neighbors()
    leases = discover_dhcp_leases()
    mac_to_ip: Dict[str, str] = { _normalize_mac(v): k for k, v in neighbors.items() }
    mac_to_name: Dict[str, str] = {}
    for l in leases:
        if l.get("mac") and l.get("ip"):
            mac_to_ip[_normalize_mac(l["mac"]) ] = l["ip"]  # type: ignore[index]
            if l.get("name"):
                mac_to_name[_normalize_mac(l["mac"]) ] = l["name"]  # type: ignore[index]

    for info in ifaces:
        ifname = info.get("ifname")
        itype = (info.get("type") or "").lower()
        if not ifname:
            continue
        # Prefer AP mode for enumerating associated stations
        if itype not in ("ap",):
            continue
        macs = _iw_station_dump(ifname)
        for mac in macs:
            ip = mac_to_ip.get(mac)
            name = mac_to_name.get(mac)
            stations.append({
                "mac": mac,
                "ip": ip,
                "name": name or (ip or mac),
                "status": "online",
                "type": "wifi-station",
            })
    return stations


def _reverse_dns(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ip


def _arp_neighbors() -> Dict[str, str]:
    """Return map of ip->mac from `ip neigh show` (Linux)."""
    neighbors: Dict[str, str] = {}
    if platform.system().lower() == "linux" and _which("ip"):
        rc, out, _ = _sh(["ip", "neigh", "show"])  # e.g., "192.168.1.10 dev eth0 lladdr aa:bb:... REACHABLE"
        if rc == 0:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[2] == "dev":
                    ip = parts[0]
                    # Find lladdr MAC if present
                    mac = None
                    for i, token in enumerate(parts):
                        if token == "lladdr" and i + 1 < len(parts):
                            mac = parts[i + 1]
                            break
                    if mac:
                        neighbors[ip] = mac
    return neighbors


def _parse_arp_scan(output: str) -> List[Dict[str, Optional[str]]]:
    """Parse arp-scan output into a list of {'ip','mac','vendor'} dicts."""
    devices: List[Dict[str, Optional[str]]] = []
    for line in output.splitlines():
        # typical: 192.168.1.10	AA:BB:CC:DD:EE:FF	Apple, Inc.
        line = line.strip()
        if not line or line.startswith("Interface:") or line.startswith("Starting arp-scan") or line.startswith("Ending arp-scan"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) >= 2 and _is_ipv4(parts[0]):
            ip = parts[0]
            mac = parts[1]
            vendor = parts[2] if len(parts) >= 3 else None
            devices.append({
                "ip": ip,
                "mac": mac,
                "vendor": vendor,
            })
    return devices


def _parse_nmap_sn(output: str) -> List[Dict[str, Optional[str]]]:
    """Parse `nmap -sn` output into host dictionaries (ip, name, mac, vendor)."""
    devices: List[Dict[str, Optional[str]]] = []
    # Nmap -sn normal output:
    # Nmap scan report for hostname (192.168.1.10)
    # Host is up (0.0060s latency).
    # MAC Address: AA:BB:... (Vendor)
    current: Dict[str, Optional[str]] = {}
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Nmap scan report for"):
            # flush previous
            if current.get("ip"):
                devices.append(current)
            current = {"ip": None, "name": None, "mac": None, "vendor": None}
            # extract IP in parentheses or last token
            if "(" in line and ")" in line:
                ip = line.split("(")[-1].split(")")[0].strip()
                name = line.split("for", 1)[1].split("(")[0].strip()
                current.update({"ip": ip, "name": name})
            else:
                tokens = line.split()
                ip = tokens[-1]
                current.update({"ip": ip})
        elif line.startswith("MAC Address:"):
            rest = line.split(":", 1)[1].strip()
            mac = rest.split()[0]
            vendor = rest.split("(")[-1].split(")")[0] if "(" in rest else None
            current.update({"mac": mac, "vendor": vendor})
    if current.get("ip"):
        devices.append(current)
    return devices


def _is_ipv4(s: str) -> bool:
    """Return True if the string is a valid IPv4 address."""
    try:
        ipaddress.IPv4Address(s)
        return True
    except Exception:
        return False


def _ping_once(host: str, timeout_sec: float = 0.8) -> bool:
    """Send one ICMP ping to host and return True if alive."""
    if not _which("ping"):
        return False
    if platform.system().lower() == "windows":
        cmd = ["ping", "-n", "1", "-w", str(int(timeout_sec * 1000)), host]
    else:
        # Linux/macOS: -c 1 (one packet), -W timeout (in seconds Linux, ms on macOS)
        if platform.system().lower() == "darwin":
            cmd = ["ping", "-c", "1", "-W", str(int(timeout_sec * 1000)), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(timeout_sec)), host]
    rc, _, _ = _sh(cmd, timeout=max(1, int(timeout_sec * 2)))
    return rc == 0


def _ping_sweep(cidr: str, include_offline: bool, max_workers: int = 128, timeout_sec: float = 0.8) -> List[Dict[str, Optional[str]]]:
    """Ping-scan all hosts in a CIDR concurrently and return device dicts."""
    network = ipaddress.ip_network(cidr, strict=False)
    hosts = [str(h) for h in network.hosts()]
    devices: List[Dict[str, Optional[str]]] = []
    if not hosts:
        return devices

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_to_ip = {ex.submit(_ping_once, ip, timeout_sec): ip for ip in hosts}
        for fut in as_completed(fut_to_ip):
            ip = fut_to_ip[fut]
            alive = False
            try:
                alive = fut.result()
            except Exception:
                alive = False
            if alive or include_offline:
                name = _reverse_dns(ip) if alive else ip
                devices.append({
                    "ip": ip,
                    "name": name,
                    "status": "online" if alive else "offline",
                    "type": "unknown",
                })
    return devices


def _merge_mac_vendor(devices: List[Dict[str, Optional[str]]], neighbors: Dict[str, str]) -> None:
    """Merge ARP neighbor MAC addresses into the device list in-place."""
    ip_to_dev = {d.get("ip"): d for d in devices if d.get("ip")}
    for ip, mac in neighbors.items():
        if ip in ip_to_dev:
            ip_to_dev[ip]["mac"] = ip_to_dev[ip].get("mac") or mac


# -------------------------
# OUI (MAC vendor) mapping
# -------------------------
_OUI_CACHE: Optional[Dict[str, str]] = None


def _load_oui_map() -> Dict[str, str]:
    """Load OUI vendor prefixes from packaged JSON; memoized in global cache."""
    global _OUI_CACHE
    if _OUI_CACHE is not None:
        return _OUI_CACHE
    # Look for packaged OUI JSON
    here = os.path.abspath(os.path.dirname(__file__))
    candidates = [
        os.path.join(here, "data", "oui_prefixes.json"),
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    _OUI_CACHE = json.load(f)
                    return _OUI_CACHE or {}
        except Exception:
            pass
    _OUI_CACHE = {}
    return _OUI_CACHE


def _normalize_mac(mac: str) -> str:
    """Normalize MAC address to uppercase colon-separated form."""
    return mac.strip().upper().replace("-", ":")


def _vendor_from_mac(mac: Optional[str]) -> Optional[str]:
    """Lookup vendor string from normalized MAC address prefix, if available."""
    if not mac:
        return None
    mac = _normalize_mac(mac)
    if not re.match(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$", mac):
        return None
    prefix = ":".join(mac.split(":")[:3])
    oui = _load_oui_map()
    return oui.get(prefix)


# -------------------------
# SSDP/UPnP discovery
# -------------------------
def _parse_ssdp_response(data: bytes) -> Dict[str, str]:
    """Parse a single SSDP response packet into a header dict (best-effort)."""
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        return {}
    headers: Dict[str, str] = {}
    for i, line in enumerate(text.split("\r\n")):
        if i == 0:
            headers["_status"] = line.strip()
            continue
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip().upper()] = v.strip()
    return headers


def discover_ssdp_devices(timeout: float = 2.0) -> List[Dict[str, Optional[str]]]:
    """Broadcast SSDP M-SEARCH and collect best-effort device hints."""
    group = ("239.255.255.250", 1900)
    msg = ("M-SEARCH * HTTP/1.1\r\n"
           "HOST: 239.255.255.250:1900\r\n"
           "MAN: \"ssdp:discover\"\r\n"
           "MX: 2\r\n"
           "ST: ssdp:all\r\n\r\n").encode("utf-8")

    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM, _socket.IPPROTO_UDP)
    sock.setsockopt(_socket.IPPROTO_IP, _socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)

    devices: Dict[str, Dict[str, Optional[str]]] = {}
    try:
        # Send a few probes (helps across multiple NICs)
        for _ in range(2):
            try:
                sock.sendto(msg, group)
            except Exception:
                pass
        start = time.time()
        while time.time() - start < timeout:
            try:
                data, addr = sock.recvfrom(65535)
            except _socket.timeout:
                break
            except Exception:
                break
            ip = addr[0]
            hdr = _parse_ssdp_response(data)
            if not ip or not hdr:
                continue
            name = hdr.get("SERVER") or hdr.get("ST") or hdr.get("USN") or ip
            devices[ip] = {
                "ip": ip,
                "name": name,
                "status": "online",
                "type": "ssdp",
            }
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return list(devices.values())


# -------------------------
# mDNS/Bonjour discovery (optional)
# -------------------------
def discover_mdns_devices(timeout: float = 3.0) -> List[Dict[str, Optional[str]]]:
    """Discover mDNS/Bonjour services using zeroconf if available."""
    try:
        from zeroconf import ServiceBrowser, Zeroconf  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        return []
    results: Dict[str, Dict[str, Optional[str]]] = {}

    class _Listener:
        def add_service(self, zc, stype, name):  # pragma: no cover - requires network
            try:
                info = zc.get_service_info(stype, name, 1000)
                if info and info.addresses:
                    for addr in info.addresses:
                        ip = _socket.inet_ntoa(addr)
                        results[ip] = {
                            "ip": ip,
                            "name": info.name or ip,
                            "status": "online",
                            "type": "mdns",
                        }
            except Exception:
                pass

    zc = Zeroconf()
    try:
        listener = _Listener()
        # Common HTTP service
        ServiceBrowser(zc, "_http._tcp.local.", listener)  # type: ignore[arg-type]
        time.sleep(timeout)
    finally:
        try:
            zc.close()
        except Exception:
            pass
    return list(results.values())


# -------------------------
# DHCP leases discovery
# -------------------------
def _read_file_lines(path: str) -> List[str]:
    """Read a file's lines with best-effort error handling."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().splitlines()
    except Exception:
        return []


def parse_dnsmasq_leases(path: str = "/var/lib/misc/dnsmasq.leases") -> List[Dict[str, str]]:
    """Parse dnsmasq leases file ("<expiry> <mac> <ip> <hostname> <client-id>")."""
    leases: List[Dict[str, str]] = []
    for line in _read_file_lines(path):
        parts = line.strip().split()
        if len(parts) >= 4 and _is_ipv4(parts[2]):
            leases.append({
                "ip": parts[2],
                "mac": parts[1],
                "name": parts[3] if parts[3] != "*" else "",
            })
    return leases


def parse_dhcpd_leases(path: str = "/var/lib/dhcp/dhcpd.leases") -> List[Dict[str, str]]:
    """Parse ISC dhcpd leases (best-effort)."""
    leases: List[Dict[str, str]] = []
    content = "\n".join(_read_file_lines(path))
    # naive split by 'lease <ip> {' ... '}'
    for block in re.findall(r"lease\s+(\d+\.\d+\.\d+\.\d+)\s*\{(.*?)\}", content, re.S):
        ip, body = block
        if not _is_ipv4(ip):
            continue
        mac_match = re.search(r"hardware\s+ethernet\s+([0-9a-f:]+);", body, re.I)
        name_match = re.search(r"client-hostname\s+\"([^\"]+)\";", body, re.I)
        leases.append({
            "ip": ip,
            "mac": mac_match.group(1) if mac_match else "",
            "name": name_match.group(1) if name_match else "",
        })
    return leases


def discover_dhcp_leases() -> List[Dict[str, str]]:
    """Return normalized DHCP lease entries with MAC addresses uppercased."""
    leases = parse_dnsmasq_leases() + parse_dhcpd_leases()
    # Normalize MAC format
    for l in leases:
        if l.get("mac"):
            l["mac"] = _normalize_mac(l["mac"])  # type: ignore[index]
    return leases


def scan_network(subnet: Optional[str] = None,
                 include_offline: bool = False,
                 method: str = "auto",
                 timeout_sec: float = 0.8,
                 deep_discovery: bool = False) -> List[Dict[str, Optional[str]]]:
    """
    Scan a network and return device dictionaries.

    Args:
        subnet: CIDR string like "192.168.1.0/24". If None, auto-discover.
        include_offline: include hosts that didn't respond (ping sweep only).
        method: 'auto' | 'arp-scan' | 'nmap' | 'ping'.
        timeout_sec: per-host timeout for ping.
    """
    if subnet == "all":
        # Aggregate across all discovered subnets (avoid duplicates by IP)
        results: Dict[str, Dict[str, Optional[str]]] = {}
        subnets = discover_all_local_cidrs()
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(subnets)))) as ex:
            futures = [ex.submit(scan_network, s, include_offline, method, timeout_sec, deep_discovery) for s in subnets]
            for fut in as_completed(futures):
                try:
                    lst = fut.result() or []
                except Exception:
                    lst = []
                for dev in lst:
                    ip = dev.get("ip")
                    if ip and ip not in results:
                        results[ip] = dev
        return list(results.values())

    cidr = subnet or discover_local_cidr()
    if not cidr:
        return []

    devices: List[Dict[str, Optional[str]]] = []
    backends_tried: List[str] = []

    def normalize(items: Iterable[Dict[str, Optional[str]]]) -> List[Dict[str, Optional[str]]]:
        out: List[Dict[str, Optional[str]]] = []
        for d in items:
            ip = d.get("ip")
            if not ip or not _is_ipv4(str(ip)):
                continue
            name = d.get("name") or _reverse_dns(str(ip))
            status = d.get("status") or "online"
            out.append({
                "name": name,
                "ip": str(ip),
                "status": status,
                "type": d.get("type") or "unknown",
                "mac": d.get("mac"),
                "vendor": d.get("vendor"),
            })
        return out

    # Decide backend
    chosen = method
    if method == "auto":
        if _which("arp-scan"):
            chosen = "arp-scan"
        elif _which("nmap"):
            chosen = "nmap"
        else:
            chosen = "ping"

    # 1) ARP-SCAN
    if chosen == "arp-scan":
        backends_tried.append("arp-scan")
        rc, out, err = _sh(["arp-scan", "--localnet", "--numeric", "--timeout=200"], timeout=30)
        if rc == 0 and out:
            parsed = _parse_arp_scan(out)
            devices = normalize(parsed)
        else:
            # Fallback to ping
            chosen = "ping"

    # 2) NMAP -sn
    if chosen == "nmap":
        backends_tried.append("nmap")
        rc, out, err = _sh(["nmap", "-sn", cidr], timeout=90)
        if rc == 0 and out:
            parsed = _parse_nmap_sn(out)
            devices = normalize(parsed)
        else:
            chosen = "ping"

    # 3) Concurrent PING sweep
    if chosen == "ping":
        backends_tried.append("ping")
        devices = _ping_sweep(cidr, include_offline=include_offline, timeout_sec=timeout_sec)

    # Enrich with ARP neighbors if possible
    try:
        neighbors = _arp_neighbors()
        _merge_mac_vendor(devices, neighbors)
    except Exception:
        pass

    # Add vendor via OUI DB if missing
    try:
        for d in devices:
            if not d.get("vendor") and d.get("mac"):
                d["vendor"] = _vendor_from_mac(d.get("mac"))
    except Exception:
        pass

    # Optional deep discovery (SSDP, mDNS, DHCP leases)
    if deep_discovery:
        try:
            ssdp = discover_ssdp_devices(timeout=2.0)
        except Exception:
            ssdp = []
        try:
            mdns = discover_mdns_devices(timeout=3.0)
        except Exception:
            mdns = []
        try:
            leases = discover_dhcp_leases()
        except Exception:
            leases = []

        # Merge by IP first
        idx = {d.get("ip"): d for d in devices if d.get("ip")}

        for extra in ssdp + mdns:
            ip = extra.get("ip")
            if not ip:
                continue
            if ip in idx:
                base = idx[ip]
                base["name"] = base.get("name") or extra.get("name")
                base["type"] = base.get("type") if base.get("type") != "unknown" else extra.get("type") or "unknown"
                # status remains whatever scan concluded; keep 'online'
            else:
                idx[ip] = {
                    "ip": ip,
                    "name": extra.get("name") or ip,
                    "status": extra.get("status") or "online",
                    "type": extra.get("type") or "unknown",
                }

        # Merge DHCP leases (names/MACs)
        for lease in leases:
            ip = lease.get("ip")
            if not ip:
                continue
            mac = lease.get("mac")
            name = lease.get("name")
            if ip in idx:
                base = idx[ip]
                base["mac"] = base.get("mac") or mac
                base["name"] = base.get("name") or name or base.get("name")
                if not base.get("vendor") and mac:
                    base["vendor"] = _vendor_from_mac(mac)
            elif include_offline:
                idx[ip] = {
                    "ip": ip,
                    "name": name or ip,
                    "status": "offline",
                    "type": "unknown",
                    "mac": mac,
                    "vendor": _vendor_from_mac(mac) if mac else None,
                }

        devices = list(idx.values())

    # Ensure online/offline labels exist
    for d in devices:
        if d.get("status") not in ("online", "offline"):
            d["status"] = "online"

    return devices


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="EZ-Panel network scan")
    parser.add_argument("--cidr", help="CIDR to scan, e.g., 192.168.1.0/24")
    parser.add_argument("--method", default="auto", choices=["auto", "arp-scan", "nmap", "ping"], help="Scan backend to use")
    parser.add_argument("--include-offline", action="store_true", help="Include offline hosts (ping sweep)")
    parser.add_argument("--timeout", type=float, default=0.8, help="Per-host timeout (seconds)")
    args = parser.parse_args()

    cidr = args.cidr or discover_local_cidr()
    if not cidr:
        print("Could not determine local CIDR. Provide --cidr.")
        raise SystemExit(2)

    print(f"Scanning {cidr} using method={args.method} ...")
    results = scan_network(subnet=cidr, include_offline=args.include_offline, method=args.method, timeout_sec=args.timeout)
    for d in results:
        print(json.dumps(d))
