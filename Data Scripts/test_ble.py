import asyncio
import time
from bleak import BleakClient, BleakScanner

# Match these exactly to your ESP32 firmware
DEVICE_NAME = "CYD_ADS1298_Sim"
CHARACTERISTIC_UUID_TX = "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"

# Test configuration
TEST_DURATION_SECONDS = 60
BATCH_SIZE = 15
EXPECTED_PACKETS_PER_SECOND = 1000 / BATCH_SIZE  # ~66.66 packets/sec

packet_timestamps = []
packet_count = 0

def notification_handler(sender, data):
    global packet_count
    # Record the exact moment the packet arrives
    packet_timestamps.append(time.time())
    packet_count += 1

async def main():
    print(f"Scanning for {DEVICE_NAME}...")
    devices = await BleakScanner.discover()
    target_device = next((d for d in devices if d.name == DEVICE_NAME), None)

    if not target_device:
        print(f"Could not find {DEVICE_NAME}. Make sure it is on.")
        return

    print(f"Found {DEVICE_NAME} at {target_device.address}. Connecting...")
    
    async with BleakClient(target_device) as client:
        print("Connected! Subscribing to TX characteristic...")
        await client.start_notify(CHARACTERISTIC_UUID_TX, notification_handler)
        
        print(f"Listening for {TEST_DURATION_SECONDS} seconds...")
        
        # Check connection status every second instead of sleeping blindly
        for _ in range(TEST_DURATION_SECONDS):
            if not client.is_connected:
                print("\n[WARNING] Device disconnected unexpectedly during the test!")
                break
            await asyncio.sleep(1)
        
        print("\nTest complete. Stopping notifications...")
        if client.is_connected:
            await client.stop_notify(CHARACTERISTIC_UUID_TX)
        
        # --- CALCULATE METRICS ---
        expected_packets = int(TEST_DURATION_SECONDS * EXPECTED_PACKETS_PER_SECOND) # Should be 4000
        packet_loss = expected_packets - packet_count
        # Prevent negative packet loss if a stray packet arrives right at the cutoff
        packet_loss = max(0, packet_loss) 
        packet_loss_percent = (packet_loss / expected_packets) * 100 if expected_packets > 0 else 0
        
        print("\n" + "="*30)
        print("📊 TRANSMISSION RESULTS")
        print("="*30)
        print(f"Test Duration:      {TEST_DURATION_SECONDS} seconds")
        print(f"Expected Packets:   {expected_packets}")
        print(f"Received Packets:   {packet_count}")
        print(f"Packet Loss:        {packet_loss} packets ({packet_loss_percent:.4f}%)")
        
        if len(packet_timestamps) > 1:
            intervals = [ (packet_timestamps[i] - packet_timestamps[i-1])*1000 for i in range(1, len(packet_timestamps)) ]
            avg_interval = sum(intervals) / len(intervals)
            max_jitter = max(intervals)
            min_jitter = min(intervals)
            
            print(f"\n⏱️ TIMING & JITTER")
            print(f"Expected Interval:  {BATCH_SIZE}.00 ms")
            print(f"Average Interval:   {avg_interval:.2f} ms")
            print(f"Min Interval:       {min_jitter:.2f} ms")
            print(f"Max Interval:       {max_jitter:.2f} ms")
        
if __name__ == "__main__":
    asyncio.run(main())