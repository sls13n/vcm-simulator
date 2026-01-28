import socket
import time

# --- CONFIGURATION ---
broadcast_ip = "198.18.255.255"   # change to your target broadcast address
port = 50000                      # UDP port
interval_ms = 1000                # send every 1000ms (1 second)
# ---------------------

# Hex payload from your capture
# ihu_payload_hex = (
#     "ff ff ff 01 00 00 00 0c ff 01 06 51 "
#     "02 06 01 00 03 00 00 00"
# )

# Base payload template (the dynamic byte will be inserted at position 11)
vcm_payload_template = [
    0xff, 0xff, 0xff, 0x01, 0x00, 0x00, 0x00, 0x0c, 0xff, 0x01,
    0x06,
    0x00,  # This byte will be dynamically changed (starts at 0x00)
    0x02, 0x06, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00
]

# Initialize counter
counter = 0x00

# Create UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

print(f"Sending {len(vcm_payload_template)} bytes to {broadcast_ip}:{port} every {interval_ms}ms ...")
print("Press Ctrl+C to stop")

try:
    packet_count = 0
    while True:
        # Update the dynamic byte at position 11
        vcm_payload_template[11] = counter
        
        # Convert to bytes and send
        payload = bytes(vcm_payload_template)
        sock.sendto(payload, (broadcast_ip, port))
        
        packet_count += 1
        print(f"Sent packet #{packet_count} (counter: 0x{counter:02x})", end='\r')
        
        # Increment counter and wrap around at 0xFF
        counter = (counter + 1) % 0x100
        
        time.sleep(interval_ms / 1000.0)  # convert ms to seconds
except KeyboardInterrupt:
    print(f"\nStopped. Total packets sent: {packet_count}")
finally:
    sock.close()
    print("Done.")
