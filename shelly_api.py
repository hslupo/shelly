"""Shelly API client – unterstützt Gen1 (Plug, Plug S) und Gen2 (Plus Plug S)."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import socket
import requests
from dataclasses import dataclass
from typing import Optional


TIMEOUT = 5  # Sekunden
DISCOVERY_TIMEOUT = 0.8  # Sekunden pro Host bei Netzwerksuche


def _local_private_ipv4_addresses() -> set[str]:
    """Liefert lokale private IPv4-Adressen des Hosts."""
    host = socket.gethostname()
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
    except socket.gaierror:
        infos = []

    addresses: set[str] = set()
    for info in infos:
        if not info[4] or not info[4][0]:
            continue
        ip_str = str(info[4][0])
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if isinstance(ip, ipaddress.IPv4Address) and ip.is_private and not ip.is_loopback:
            addresses.add(ip_str)
    return addresses


@dataclass
class ShellyStatus:
    name: str
    ip: str
    online: bool
    relay_on: bool = False
    power_w: float = 0.0
    total_kwh: float = 0.0
    voltage_v: Optional[float] = None
    current_a: Optional[float] = None
    temperature_c: Optional[float] = None
    error: str = ""
    gen: int = 1


def _local_private_networks() -> list[ipaddress.IPv4Network]:
    """Ermittelt private /24-Netze aus den lokalen IPv4-Adressen."""
    networks: list[ipaddress.IPv4Network] = []
    seen: set[str] = set()
    for ip_str in _local_private_ipv4_addresses():
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not isinstance(ip, ipaddress.IPv4Address):
            continue
        if not ip.is_private or ip.is_loopback:
            continue

        net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
        net_key = str(net)
        if net_key not in seen:
            seen.add(net_key)
            networks.append(net)

    return networks


def _probe_shelly_host(ip: str, timeout: float) -> Optional[dict]:
    """Prüft einen Host auf ein Shelly-Gerät und liefert Basisinfos."""
    try:
        r = requests.get(f"http://{ip}/shelly", timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    try:
        gen = int(data.get("gen", 1))
    except (TypeError, ValueError):
        gen = 1
    default_name = f"Shelly {ip}"
    return {
        "name": data.get("name") or default_name,
        "ip": ip,
        "gen": gen,
        "model": data.get("model") or data.get("type") or "",
        "id": data.get("id") or data.get("mac") or "",
    }


def discover_devices(timeout: float = DISCOVERY_TIMEOUT, max_workers: int = 64) -> list[dict]:
    """Sucht Shelly-Geräte im lokalen privaten /24-Netz und liefert gefundene Geräte."""
    networks = _local_private_networks()
    if not networks:
        return []

    local_ips = _local_private_ipv4_addresses()

    candidates: list[str] = []
    for net in networks:
        for host in net.hosts():
            ip_str = str(host)
            if ip_str in local_ips:
                continue
            candidates.append(ip_str)

    discovered: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_probe_shelly_host, ip, timeout) for ip in candidates]
        for future in as_completed(futures):
            result = future.result()
            if result:
                discovered.append(result)

    discovered.sort(key=lambda d: tuple(int(p) for p in d["ip"].split(".")))
    return discovered


def _fetch_gen1(ip: str, name: str) -> ShellyStatus:
    status = ShellyStatus(name=name, ip=ip, online=False, gen=1)
    try:
        r = requests.get(f"http://{ip}/status", timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()

        relay = data.get("relays", [{}])[0]
        meter = data.get("meters", [{}])[0]

        status.online = True
        status.relay_on = relay.get("ison", False)
        status.power_w = meter.get("power", 0.0)
        status.total_kwh = round(meter.get("total", 0.0) / 60.0, 3)  # Wh-Minuten → kWh
        status.voltage_v = data.get("voltage")
        # Gen1 Plug S liefert Temperatur
        tmp = data.get("tmp") or data.get("temperature")
        if isinstance(tmp, dict):
            status.temperature_c = tmp.get("tC")
        elif isinstance(tmp, (int, float)):
            status.temperature_c = tmp
    except requests.exceptions.ConnectionError:
        status.error = "Verbindung fehlgeschlagen"
    except requests.exceptions.Timeout:
        status.error = "Zeitüberschreitung"
    except Exception as exc:
        status.error = str(exc)
    return status


def _fetch_gen2(ip: str, name: str) -> ShellyStatus:
    status = ShellyStatus(name=name, ip=ip, online=False, gen=2)
    try:
        r = requests.get(f"http://{ip}/rpc/Shelly.GetStatus", timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()

        switch = data.get("switch:0", {})
        status.online = True
        status.relay_on = switch.get("output", False)
        status.power_w = switch.get("apower", 0.0)
        status.total_kwh = switch.get("aenergy", {}).get("total", 0.0) / 1000.0
        status.voltage_v = switch.get("voltage")
        status.current_a = switch.get("current")
        tmp = switch.get("temperature", {})
        status.temperature_c = tmp.get("tC") if isinstance(tmp, dict) else None
    except requests.exceptions.ConnectionError:
        status.error = "Verbindung fehlgeschlagen"
    except requests.exceptions.Timeout:
        status.error = "Zeitüberschreitung"
    except Exception as exc:
        status.error = str(exc)
    return status


def detect_generation(ip: str) -> int:
    """Versucht zu ermitteln, ob es sich um ein Gen1- oder Gen2-Gerät handelt."""
    try:
        r = requests.get(f"http://{ip}/shelly", timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        gen = data.get("gen", 1)
        return int(gen)
    except Exception:
        return 1  # Fallback auf Gen1


def fetch_device(ip: str, name: str, gen: Optional[int] = None) -> ShellyStatus:
    """Lädt den Status eines Shelly-Geräts. Erkennt die Generation automatisch, falls nicht angegeben."""
    if gen is None:
        gen = detect_generation(ip)
    if gen >= 2:
        return _fetch_gen2(ip, name)
    return _fetch_gen1(ip, name)
