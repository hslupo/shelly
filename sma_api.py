"""SMA Wechselrichter API – Modbus TCP (Sunny Tripower STP5.0-3SE-40)."""
from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

try:
    from pymodbus.client import ModbusTcpClient
    PYMODBUS_OK = True
except ImportError:
    PYMODBUS_OK = False

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

MODBUS_PORT = 502
DEFAULT_UNIT_ID = 3       # SMA-Standardwert
TIMEOUT = 3.0
SCAN_TIMEOUT = 0.5

# SMA Modbus-Register (Sunny Tripower, FC3 – Read Holding Registers)
_REG_POWER_W        = 30775   # Wirkleistung AC gesamt (W),       S32
_REG_DAY_YIELD_WH   = 30517   # Tagesertrag (Wh),                 U32
_REG_TOTAL_YIELD_WH = 30529   # Gesamtertrag (Wh),                U32
_REG_VOLTAGE_L1     = 30769   # Spannung L1 (1/100 V),            U32
_REG_VOLTAGE_L2     = 30771   # Spannung L2 (1/100 V),            U32
_REG_VOLTAGE_L3     = 30773   # Spannung L3 (1/100 V),            U32
_REG_FREQUENCY      = 30803   # Netzfrequenz (1/100 Hz),          U32
_REG_STATUS         = 30201   # Betriebsstatus,                   U32

_NAN_S32 = 0x80000000
_NAN_U32 = 0xFFFFFFFF

STATUS_NAMES: dict[int, str] = {
    35:  "Fehler",
    303: "Aus",
    307: "OK",
    308: "Warnung",
    455: "Störung",
}

# ---------------------------------------------------------------------------
# Datenklasse
# ---------------------------------------------------------------------------

@dataclass
class SMAStatus:
    ip: str
    online: bool
    power_w: float = 0.0
    day_yield_kwh: float = 0.0
    total_yield_kwh: float = 0.0
    voltage_l1: Optional[float] = None
    voltage_l2: Optional[float] = None
    voltage_l3: Optional[float] = None
    frequency_hz: Optional[float] = None
    device_status: str = ""
    error: str = ""

# ---------------------------------------------------------------------------
# Interne Helfer
# ---------------------------------------------------------------------------

def _to_s32(regs: list[int]) -> Optional[int]:
    val = (regs[0] << 16) | regs[1]
    if val == _NAN_S32:
        return None
    return val - 0x100000000 if val >= 0x80000000 else val


def _to_u32(regs: list[int]) -> Optional[int]:
    val = (regs[0] << 16) | regs[1]
    return None if val == _NAN_U32 else val


def _read_reg(client, address: int, unit_id: int) -> Optional[list[int]]:
    try:
        r = client.read_holding_registers(address=address, count=2, slave=unit_id)
        if r.isError():
            return None
        return list(r.registers)
    except Exception:
        return None


def _local_ipv4_addresses() -> set[str]:
    host = socket.gethostname()
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
    except socket.gaierror:
        infos = []
    result: set[str] = set()
    for info in infos:
        if not info[4] or not info[4][0]:
            continue
        ip_str = str(info[4][0])
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if isinstance(ip, ipaddress.IPv4Address) and ip.is_private and not ip.is_loopback:
            result.add(ip_str)
    return result


def _local_networks() -> list[ipaddress.IPv4Network]:
    nets: list[ipaddress.IPv4Network] = []
    seen: set[str] = set()
    for ip_str in _local_ipv4_addresses():
        net = ipaddress.IPv4Network(f"{ip_str}/24", strict=False)
        if str(net) not in seen:
            seen.add(str(net))
            nets.append(net)
    return nets

# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def fetch_sma_status(
    ip: str, port: int = MODBUS_PORT, unit_id: int = DEFAULT_UNIT_ID
) -> SMAStatus:
    """Liest den Status des SMA-Wechselrichters über Modbus TCP."""
    if not PYMODBUS_OK:
        return SMAStatus(ip=ip, online=False, error="pymodbus nicht installiert")

    status = SMAStatus(ip=ip, online=False)
    client = ModbusTcpClient(host=ip, port=port, timeout=TIMEOUT)
    try:
        if not client.connect():
            status.error = "Verbindung fehlgeschlagen"
            return status

        regs = _read_reg(client, _REG_POWER_W, unit_id)
        if regs is not None:
            val = _to_s32(regs)
            if val is not None:
                status.power_w = float(val)
                status.online = True

        regs = _read_reg(client, _REG_DAY_YIELD_WH, unit_id)
        if regs is not None:
            val = _to_u32(regs)
            if val is not None:
                status.day_yield_kwh = val / 1000.0

        regs = _read_reg(client, _REG_TOTAL_YIELD_WH, unit_id)
        if regs is not None:
            val = _to_u32(regs)
            if val is not None:
                status.total_yield_kwh = val / 1000.0

        regs = _read_reg(client, _REG_VOLTAGE_L1, unit_id)
        if regs is not None:
            val = _to_u32(regs)
            if val is not None:
                status.voltage_l1 = val / 100.0

        regs = _read_reg(client, _REG_VOLTAGE_L2, unit_id)
        if regs is not None:
            val = _to_u32(regs)
            if val is not None:
                status.voltage_l2 = val / 100.0

        regs = _read_reg(client, _REG_VOLTAGE_L3, unit_id)
        if regs is not None:
            val = _to_u32(regs)
            if val is not None:
                status.voltage_l3 = val / 100.0

        regs = _read_reg(client, _REG_FREQUENCY, unit_id)
        if regs is not None:
            val = _to_u32(regs)
            if val is not None:
                status.frequency_hz = val / 100.0

        regs = _read_reg(client, _REG_STATUS, unit_id)
        if regs is not None:
            val = _to_u32(regs)
            if val is not None:
                status.device_status = STATUS_NAMES.get(val, str(val))

    except Exception as exc:
        status.error = str(exc)
    finally:
        client.close()

    return status


def _probe_modbus_port(ip: str, timeout: float = SCAN_TIMEOUT) -> Optional[str]:
    """Prüft, ob Port 502 an dieser IP erreichbar ist."""
    try:
        with socket.create_connection((ip, MODBUS_PORT), timeout=timeout):
            return ip
    except Exception:
        return None


def discover_sma_devices(
    timeout: float = SCAN_TIMEOUT, max_workers: int = 64
) -> list[str]:
    """Scannt das lokale /24-Netz auf offene Modbus-Ports und liefert IP-Adressen."""
    networks = _local_networks()
    local_ips = _local_ipv4_addresses()

    candidates = [
        str(host)
        for net in networks
        for host in net.hosts()
        if str(host) not in local_ips
    ]

    found: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_probe_modbus_port, ip, timeout) for ip in candidates]
        for future in as_completed(futures):
            result = future.result()
            if result:
                found.append(result)

    found.sort(key=lambda ip: tuple(int(p) for p in ip.split(".")))
    return found
