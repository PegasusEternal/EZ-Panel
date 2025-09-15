import subprocess
import platform
import socket
import ipaddress
import shutil

def ping(host):
    """Ping a host once. Returns True if alive, False otherwise."""
    if not shutil.which("ping"):
        return False

    param = "-n" if platform.system().lower() == "windows" else "-c"
    try:
        subprocess.run(
            ["ping", param, "1", str(host)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

def get_local_subnet():
    """Detect the local subnet automatically. Returns CIDR format."""
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        if local_ip.startswith("127."):
            return "192.168.1.0/24"  # fallback
        network = ipaddress.ip_network(local_ip + "/24", strict=False)
        return str(network)
    except Exception:
        return None

def scan_network(subnet=None, include_offline=False):
    """
    Scan network and return a list of devices.
    
    Each device dict contains:
        - name: hostname or IP fallback
        - ip: device IP
        - status: 'online' or 'offline'
        - type: optional, default 'unknown'
    """
    if subnet is None:
        subnet = get_local_subnet()
        if subnet is None:
            return []

    devices = []
    try:
        network = ipaddress.ip_network(subnet, strict=False)
        for ip in network.hosts():
            alive = ping(str(ip))
            
            if not alive and not include_offline:
                continue  # skip offline devices if not wanted
            
            try:
                hostname = socket.gethostbyaddr(str(ip))[0]
            except socket.herror:
                hostname = str(ip)

            devices.append({
                "name": hostname,
                "ip": str(ip),
                "status": "online" if alive else "offline",
                "type": "unknown"
            })
    except Exception as e:
        print(f"Error scanning network: {e}")
        return []

    return devices

# Example usage
if __name__ == "__main__":
    print("Scanning network for online devices...")
    results = scan_network()
    for device in results:
        print(device)
