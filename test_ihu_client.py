#!/usr/bin/env python3
"""
IHU Test Client - Simulates IHU for testing VCM Simulator

This client can replay the captured traffic or send custom commands.
"""

import asyncio
import socket
import time
import sys
from typing import Optional, List, Tuple
from dataclasses import dataclass

from vcm_protocol import parse_message, create_ack, VCMMessage


# Network configuration
VCM_IP = "127.0.0.1"  # localhost for testing, change to 198.18.32.1 for real VCM
VCM_PORT = 50000
IHU_PORT = 50000  # IHU listen port


@dataclass
class CapturedPacket:
    """A packet from the capture file"""
    seq_number: int
    time: str
    source: str
    destination: str
    payload: str
    is_from_ihu: bool


def load_captured_packets(csv_path: str) -> List[CapturedPacket]:
    """Load packets from CSV file"""
    import csv
    packets = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            is_from_ihu = row['source'] == "198.18.34.1"
            packets.append(CapturedPacket(
                seq_number=int(row['seq_number']),
                time=row['time'],
                source=row['source'],
                destination=row['destination'],
                payload=row['payload'],
                is_from_ihu=is_from_ihu
            ))
    return packets


class IHUClient:
    """IHU Test Client"""
    
    def __init__(self, vcm_host: str = VCM_IP, vcm_port: int = VCM_PORT):
        self.vcm_host = vcm_host
        self.vcm_port = vcm_port
        self.sock: Optional[socket.socket] = None
        self.responses: List[Tuple[str, float]] = []  # (payload, timestamp)
    
    def connect(self):
        """Create UDP socket"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(2.0)  # 2 second timeout
        # Bind to any available port (or specify IHU_PORT if needed)
        self.sock.bind(('0.0.0.0', 0))
        local_port = self.sock.getsockname()[1]
        print(f"IHU client bound to port {local_port}")
    
    def send(self, payload_hex: str) -> List[str]:
        """Send a payload and collect responses"""
        if not self.sock:
            self.connect()
        
        # Send the message
        payload_bytes = bytes.fromhex(payload_hex)
        self.sock.sendto(payload_bytes, (self.vcm_host, self.vcm_port))
        
        msg = parse_message(payload_hex)
        print(f"IHU >>> VCM: {msg}")
        
        # Collect responses (with timeout)
        responses = []
        try:
            while True:
                data, addr = self.sock.recvfrom(1024)
                response_hex = data.hex()
                responses.append(response_hex)
                
                resp_msg = parse_message(response_hex)
                print(f"VCM >>> IHU: {resp_msg}")
                
                # If we got a non-ACK response, that's usually the end
                if resp_msg and not resp_msg.is_ack:
                    # Give a tiny bit more time for any follow-up
                    self.sock.settimeout(0.1)
        except socket.timeout:
            pass
        
        self.sock.settimeout(2.0)  # Reset timeout
        return responses
    
    def send_ack(self, payload_hex: str):
        """Send an ACK for a received message"""
        if not self.sock:
            self.connect()
        
        msg = parse_message(payload_hex)
        if msg:
            ack = create_ack(msg)
            self.sock.sendto(ack.raw_bytes, (self.vcm_host, self.vcm_port))
            print(f"IHU >>> VCM (ACK): {ack}")
    
    def close(self):
        """Close the socket"""
        if self.sock:
            self.sock.close()
            self.sock = None


def interactive_mode(client: IHUClient):
    """Interactive mode for manual testing"""
    print("\n" + "=" * 60)
    print("IHU Test Client - Interactive Mode")
    print("=" * 60)
    print("Commands:")
    print("  send <hex>  - Send a raw hex payload")
    print("  ping        - Send handshake pings")
    print("  setup       - Send setup trigger")
    print("  wifi <pass> - Send WiFi password")
    print("  replay      - Replay full captured sequence")
    print("  quit        - Exit")
    print("=" * 60)
    
    while True:
        try:
            cmd = input("\nIHU> ").strip()
            
            if not cmd:
                continue
            
            parts = cmd.split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            
            if command == "quit" or command == "exit":
                break
            
            elif command == "send":
                if args:
                    client.send(args)
                else:
                    print("Usage: send <hex_payload>")
            
            elif command == "ping":
                # Send handshake pings
                print("Sending handshake pings...")
                client.send("00a4040d00000008a40d002802000000")  # ping 0d
                time.sleep(0.1)
                client.send("00a3030f00000008a30f002902000000")  # ping 0f
            
            elif command == "setup":
                print("Sending setup trigger...")
                client.send("00a4040000000009a40002320202000020")
            
            elif command == "wifi":
                if args:
                    # Encode the password
                    password = args.encode('utf-8')
                    pwd_hex = password.hex()
                    pwd_len = len(password)
                    # Format: 00a4040800000018a408024b02020000 + len + password + extra
                    payload = f"00a4040800000018a408024b02020000{pwd_len:02x}{pwd_hex}19d195cdd185cc"
                    client.send(payload)
                else:
                    # Use default from capture
                    client.send("00a4040800000018a408024b02020000086c61696b696e617319d195cdd185cc")
            
            elif command == "replay":
                replay_captured_sequence(client)
            
            else:
                print(f"Unknown command: {command}")
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
    
    print("\nExiting...")


def replay_captured_sequence(client: IHUClient):
    """Replay the captured WiFi enable sequence"""
    print("\n" + "=" * 60)
    print("Replaying captured WiFi enable sequence...")
    print("=" * 60)
    
    # Phase 1: Initial handshake
    print("\n[Phase 1] Initial Handshake")
    client.send("00a4040d00000008a40d002802000000")
    time.sleep(0.1)
    client.send("00a3030f00000008a30f002902000000")
    time.sleep(0.1)
    
    # Second round of pings
    print("\n[Phase 1] Second round of pings")
    client.send("00a4040d00000008a40d003002000000")
    time.sleep(0.1)
    client.send("00a3030f00000008a30f003102000000")
    time.sleep(0.1)
    
    # Phase 2: Setup trigger
    print("\n[Phase 2] Setup Sequence")
    responses = client.send("00a4040000000009a40002320202000020")
    time.sleep(0.1)
    
    # VCM will send setup requests, we need to respond to them
    # The state machine handles sending ACKs, we need to send responses
    
    # Respond to a31102 (sequence 50)
    print("  Responding to setup requests...")
    client.send("00a3031100000009a31102500204000000")
    time.sleep(0.1)
    
    # Respond to a31002 (sequence 51)
    client.send("00a3031000000009a31002510204000000")
    time.sleep(0.1)
    
    # Respond to first a30802 (sequence 52)
    client.send("00a3030800000009a30802520204000000")
    time.sleep(0.1)
    
    # Respond to second a30802 with flag 80 (sequence 54)
    client.send("00a3030800000009a30802540204000080")
    time.sleep(0.1)
    
    # Phase 3: Wait for SSID broadcasts
    print("\n[Phase 3] WiFi Scanning - waiting for broadcasts...")
    print("  (VCM should send SSID broadcasts every 5 seconds)")
    
    # Wait for a broadcast
    try:
        client.sock.settimeout(10.0)
        data, addr = client.sock.recvfrom(1024)
        broadcast = parse_message(data.hex())
        print(f"  Received broadcast: {broadcast}")
        client.send_ack(data.hex())
    except socket.timeout:
        print("  No broadcast received (timeout)")
    client.sock.settimeout(2.0)
    
    # Phase 4: Send WiFi password
    print("\n[Phase 4] WiFi Connection")
    responses = client.send("00a4040800000018a408024b02020000086c61696b696e617319d195cdd185cc")
    time.sleep(0.1)
    
    # VCM will send connection requests, find and respond to a30802
    # Send response to complete connection
    client.send("00a3030800000009a30802720204000080")
    time.sleep(0.1)
    
    # Phase 5: Connected
    print("\n[Phase 5] WiFi Connected - waiting for connected broadcasts...")
    try:
        client.sock.settimeout(10.0)
        data, addr = client.sock.recvfrom(1024)
        broadcast = parse_message(data.hex())
        print(f"  Received connected broadcast: {broadcast}")
        
        # Check for status 40 (connected)
        if "40" in broadcast.data:
            print("  ✓ WiFi connection confirmed (status 40)")
    except socket.timeout:
        print("  No broadcast received (timeout)")
    
    print("\n" + "=" * 60)
    print("Replay complete!")
    print("=" * 60)


def main():
    """Main entry point"""
    vcm_host = "127.0.0.1"
    vcm_port = VCM_PORT
    
    # Parse args
    if len(sys.argv) > 1:
        vcm_host = sys.argv[1]
    if len(sys.argv) > 2:
        vcm_port = int(sys.argv[2])
    
    print(f"IHU Test Client")
    print(f"Target VCM: {vcm_host}:{vcm_port}")
    
    client = IHUClient(vcm_host, vcm_port)
    client.connect()
    
    try:
        interactive_mode(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()
