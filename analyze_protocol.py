#!/usr/bin/env python3
"""
VCM Protocol Analyzer - Reverse Engineering Tool
Analyzes packet capture to understand VCM-IHU communication patterns
"""

import csv
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

IHU_IP = "198.18.34.1"
VCM_IP = "198.18.32.1"
ACK_DATA = "02700000"

@dataclass
class Packet:
    seq_number: int
    time: str
    source: str
    destination: str
    protocol: str
    source_port: int
    destination_port: int
    length: int
    payload: str
    
    # Parsed fields
    header: str = ""
    payload_length: int = 0
    subheader: str = ""
    sequence: int = 0
    data: str = ""
    
    @property
    def direction(self) -> str:
        if self.source == IHU_IP:
            return "IHU->VCM"
        return "VCM->IHU"
    
    @property
    def is_ack(self) -> bool:
        return self.data == ACK_DATA
    
    @property
    def message_type(self) -> str:
        """Extract message type from subheader first 2 bytes"""
        if len(self.subheader) >= 4:
            return self.subheader[:4]
        return ""
    
    def parse_payload(self):
        """Parse the payload into components"""
        if len(self.payload) < 22:  # Minimum: 7+1+3+1 = 12 bytes = 24 hex chars
            return
        
        self.header = self.payload[:14]  # 7 bytes
        self.payload_length = int(self.payload[14:16], 16)  # 1 byte
        self.subheader = self.payload[16:22]  # 3 bytes
        self.sequence = int(self.payload[22:24], 16)  # 1 byte
        self.data = self.payload[24:]  # Rest is data


def load_packets(csv_path: str) -> List[Packet]:
    """Load packets from CSV file"""
    packets = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pkt = Packet(
                seq_number=int(row['seq_number']),
                time=row['time'],
                source=row['source'],
                destination=row['destination'],
                protocol=row['protocol'],
                source_port=int(row['source_port']),
                destination_port=int(row['destination_port']),
                length=int(row['length']),
                payload=row['payload']
            )
            pkt.parse_payload()
            packets.append(pkt)
    return packets


def analyze_message_types(packets: List[Packet]) -> Dict[str, List[Packet]]:
    """Group packets by message type (subheader)"""
    by_type = defaultdict(list)
    for pkt in packets:
        key = f"{pkt.subheader}"
        by_type[key].append(pkt)
    return dict(by_type)


def analyze_conversations(packets: List[Packet]) -> List[List[Packet]]:
    """Group packets into request-response conversations"""
    conversations = []
    i = 0
    while i < len(packets):
        conv = [packets[i]]
        # Look for related packets (same subheader, sequence matching)
        base_subheader = packets[i].subheader
        base_seq = packets[i].sequence
        
        j = i + 1
        while j < len(packets) and j < i + 5:  # Look ahead max 5 packets
            if packets[j].subheader == base_subheader:
                conv.append(packets[j])
                if packets[j].is_ack and packets[j].direction != packets[i].direction:
                    break
            j += 1
        
        conversations.append(conv)
        i += 1
    
    return conversations


def find_state_transitions(packets: List[Packet]) -> List[Dict]:
    """Identify potential state transitions based on packet patterns"""
    transitions = []
    
    for i, pkt in enumerate(packets):
        # Skip ACKs for transition analysis
        if pkt.is_ack:
            continue
        
        transition = {
            'packet_num': pkt.seq_number,
            'time': pkt.time,
            'direction': pkt.direction,
            'subheader': pkt.subheader,
            'sequence': pkt.sequence,
            'data': pkt.data,
            'payload': pkt.payload
        }
        transitions.append(transition)
    
    return transitions


def decode_ssid_data(hex_data: str) -> str:
    """Try to decode SSID from hex data"""
    try:
        # Remove common prefixes
        data = hex_data
        result = bytes.fromhex(data).decode('utf-8', errors='replace')
        return result
    except:
        return hex_data


def main():
    print("=" * 80)
    print("VCM Protocol Analysis Report")
    print("=" * 80)
    
    packets = load_packets('../pcap_utils/enable_wifi.csv')
    
    print(f"\nTotal packets: {len(packets)}")
    
    # Count by direction
    ihu_to_vcm = [p for p in packets if p.direction == "IHU->VCM"]
    vcm_to_ihu = [p for p in packets if p.direction == "VCM->IHU"]
    print(f"IHU -> VCM: {len(ihu_to_vcm)}")
    print(f"VCM -> IHU: {len(vcm_to_ihu)}")
    
    # ACK analysis
    acks = [p for p in packets if p.is_ack]
    print(f"ACK packets: {len(acks)}")
    
    print("\n" + "=" * 80)
    print("MESSAGE TYPES (by subheader)")
    print("=" * 80)
    
    by_type = analyze_message_types(packets)
    for subheader, pkts in sorted(by_type.items()):
        directions = set(p.direction for p in pkts)
        ack_count = sum(1 for p in pkts if p.is_ack)
        non_ack = [p for p in pkts if not p.is_ack]
        print(f"\nSubheader: {subheader}")
        print(f"  Count: {len(pkts)}, ACKs: {ack_count}")
        print(f"  Directions: {directions}")
        print(f"  Non-ACK data patterns:")
        for p in non_ack[:3]:  # Show first 3
            print(f"    [{p.seq_number}] {p.direction}: seq={p.sequence:02x}, data={p.data}")
    
    print("\n" + "=" * 80)
    print("FULL PACKET FLOW (non-ACK)")
    print("=" * 80)
    
    transitions = find_state_transitions(packets)
    prev_time = None
    for t in transitions:
        time_delta = ""
        if prev_time:
            # Simple time delta (just for display)
            time_delta = f" (Δ from prev)"
        prev_time = t['time']
        
        arrow = ">>>" if t['direction'] == "IHU->VCM" else "<<<"
        print(f"[{t['packet_num']:2d}] {t['time']} {arrow} sub={t['subheader']} seq={t['sequence']:02x} data={t['data']}")
    
    print("\n" + "=" * 80)
    print("PERIODIC MESSAGE ANALYSIS")
    print("=" * 80)
    
    # Find repeated messages
    data_counts = defaultdict(list)
    for t in transitions:
        data_counts[t['payload']].append(t['packet_num'])
    
    print("\nRepeated messages (potential periodic broadcasts):")
    for payload, pkt_nums in sorted(data_counts.items(), key=lambda x: -len(x[1])):
        if len(pkt_nums) > 1:
            pkt = next(p for p in packets if p.payload == payload)
            print(f"  {payload}")
            print(f"    Count: {len(pkt_nums)}, Packets: {pkt_nums}")
            print(f"    Direction: {pkt.direction}, Subheader: {pkt.subheader}")
    
    print("\n" + "=" * 80)
    print("WIFI-RELATED MESSAGES ANALYSIS")
    print("=" * 80)
    
    # Messages with 'a408' subheader (wifi password related)
    wifi_pkts = [p for p in packets if 'a408' in p.subheader]
    print(f"\nWifi-related packets (subheader contains a408): {len(wifi_pkts)}")
    for p in wifi_pkts:
        decoded = ""
        if len(p.data) > 8:
            # Try to decode after the first 8 chars
            try:
                raw = bytes.fromhex(p.data[8:])
                decoded = f" -> decoded: {raw}"
            except:
                pass
        print(f"  [{p.seq_number}] {p.direction}: {p.payload}{decoded}")
    
    print("\n" + "=" * 80)
    print("STATE MACHINE HYPOTHESIS")
    print("=" * 80)
    
    # Group by time phases
    print("\nPhase analysis based on timing and message patterns:")
    
    phase1 = [p for p in packets if p.seq_number <= 16]
    phase2 = [p for p in packets if 17 <= p.seq_number <= 42]
    phase3 = [p for p in packets if 43 <= p.seq_number <= 54]
    phase4 = [p for p in packets if 55 <= p.seq_number <= 75]
    phase5 = [p for p in packets if p.seq_number >= 76]
    
    print(f"\nPhase 1 (pkts 1-16): Initial handshake")
    print(f"  Unique subheaders: {set(p.subheader for p in phase1)}")
    
    print(f"\nPhase 2 (pkts 17-42): Setup/Configuration")
    print(f"  Unique subheaders: {set(p.subheader for p in phase2)}")
    
    print(f"\nPhase 3 (pkts 43-54): SSID Scanning (not connected)")
    print(f"  Unique subheaders: {set(p.subheader for p in phase3)}")
    
    print(f"\nPhase 4 (pkts 55-75): WiFi Password Entry & Connection")
    print(f"  Unique subheaders: {set(p.subheader for p in phase4)}")
    
    print(f"\nPhase 5 (pkts 76-91): Connected State Broadcasting")
    print(f"  Unique subheaders: {set(p.subheader for p in phase5)}")


if __name__ == "__main__":
    main()
