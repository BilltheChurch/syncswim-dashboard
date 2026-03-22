import asyncio
from bleak import BleakClient, BleakScanner

CHAR_UUID = "abcd1234-ab12-cd34-ef56-abcdef123456"
TARGET_NAME = "NODE_A1"

packet_count = 0

async def main():
    print(f"Scanning for {TARGET_NAME}...")
    devices = await BleakScanner.discover(5.0)
    target = None
    for d in devices:
        if d.name == TARGET_NAME:
            target = d
            break

    if not target:
        print(f"{TARGET_NAME} not found. Is it powered on?")
        return

    print(f"Found {TARGET_NAME} at {target.address}, connecting...\n")

    async with BleakClient(target.address) as client:
        print(f"Connected! Receiving data for 30 seconds...\n")
        print(f"{'Node':<10} {'State':<6} {'Set':>3} {'Time':>10}  "
              f"{'ax':>7} {'ay':>7} {'az':>7}  "
              f"{'gx':>7} {'gy':>7} {'gz':>7}")
        print("-" * 90)

        global packet_count
        packet_count = 0

        def callback(sender, data):
            global packet_count
            packet_count += 1
            msg = data.decode("utf-8")
            parts = msg.split(",")
            if len(parts) >= 10:
                node, state, set_n, ts = parts[0], parts[1], parts[2], parts[3]
                ax, ay, az = parts[4], parts[5], parts[6]
                gx, gy, gz = parts[7], parts[8], parts[9]
                print(f"{node:<10} {state:<6} {set_n:>3} {ts:>10}  "
                      f"{ax:>7} {ay:>7} {az:>7}  "
                      f"{gx:>7} {gy:>7} {gz:>7}")

        await client.start_notify(CHAR_UUID, callback)
        await asyncio.sleep(30)
        await client.stop_notify(CHAR_UUID)

        print(f"\n--- Done. Received {packet_count} packets in 30s "
              f"(~{packet_count/30:.0f} Hz) ---")

asyncio.run(main())
