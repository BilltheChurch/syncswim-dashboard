import asyncio
from bleak import BleakScanner

async def scan():
    print("Scanning for BLE devices (5 seconds)...\n")
    devices = await BleakScanner.discover(5.0, return_adv=True)

    found_nodes = []
    for addr, (d, adv) in devices.items():
        name = d.name or "Unknown"
        if "NODE" in name:
            found_nodes.append(d)
            print(f"  --> {name}  |  {d.address}  |  RSSI: {adv.rssi} dBm")

    if not found_nodes:
        print("  No NODE devices found.")
        print("\n  Troubleshooting:")
        print("  - Is the M5StickC Plus2 powered on?")
        print("  - Is the screen showing NODE_A1?")
        print("  - Is Mac Bluetooth turned on?")
    else:
        print(f"\nFound {len(found_nodes)} node(s).")

asyncio.run(scan())
