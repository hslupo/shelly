from pymodbus.client import ModbusTcpClient
import struct

client = ModbusTcpClient('192.168.178.64', port=502)
if not client.connect():
    print('Verbindung fehlgeschlagen')
    exit()

def read_u32(address):
    r = client.read_holding_registers(address=address, count=2, device_id=1)
    if r.isError():
        return None, str(r)
    v = (r.registers[0] << 16) | r.registers[1]
    if v in (0x80000000, 0xFFFFFFFF, 0xFFFFFFFE):
        return None, 'NaN'
    return v, 'ok'

tests = [
    # Bekannte/funktionierende
    (30201, 'CONDITION (U32)'),
    (30203, 'OPERATION_STATUS (U32)'),
    (30775, 'AC_POWER_W (S32)'),
    (30777, 'DC_POWER_1_W (S32)'),
    (30779, 'DC_POWER_2_W (S32)'),
    (30529, 'TOTAL_YIELD_WH (U32)'),
    (30535, 'DAILY_YIELD 30535 (U32)'),
    (30953, 'TEMP_C 30953 (S32)'),
    # AC-Spannungen – Kandidaten
    (30769, 'REG_30769 (U32)'),
    (30771, 'REG_30771 (U32)'),
    (30773, 'REG_30773 (U32)'),
    (30783, 'REG_30783 (U32)'),
    (30785, 'REG_30785 (U32)'),
    (30787, 'REG_30787 (U32)'),
    # Frequenz-Kandidaten
    (30803, 'FREQ 30803 (U32)'),
    (30807, 'FREQ 30807 (U32)'),
    (30075, 'FREQ 30075 (U32)'),
    (30083, 'FREQ 30083 (U32)'),
    # DC String 1 – Kandidaten
    (30753, 'DC_STR1 30753 (U32)'),
    (30755, 'DC_STR1 30755 (U32)'),
    (30757, 'DC_STR1 30757 (U32)'),
    (30759, 'DC_STR1 30759 (U32)'),
    (30761, 'DC_STR1 30761 (U32)'),
    (30763, 'DC_STR1 30763 (U32)'),
    (30765, 'DC_STR1 30765 (U32)'),
    (30767, 'DC_STR1 30767 (U32)'),
    # DC String 2 – Kandidaten
    (30956, 'DC_STR2 30956 (U32)'),
    (30958, 'DC_STR2 30958 (U32)'),
    (30960, 'DC_STR2 30960 (U32)'),
    # Weitere AC-Strom Register
    (30795, 'REG_30795 (U32)'),
    (30797, 'REG_30797 (U32)'),
    (30799, 'REG_30799 (U32)'),
    (30801, 'REG_30801 (U32)'),
]

print('Register-Scan auf 192.168.178.64 (unit_id=1):')
for addr, name in tests:
    v, status = read_u32(addr)
    disp = str(v) if v is not None else '(' + status + ')'
    print(f'  {addr:5d} {name:40s}: {disp}')

client.close()
