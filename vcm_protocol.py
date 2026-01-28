#!/usr/bin/env python3
"""
VCM Protocol - Message encoding/decoding utilities
"""

from dataclasses import dataclass
from typing import Optional, Tuple
import struct


# Constants
ACK_DATA = "02700000"
REQUEST_PREFIX = "0200"
RESPONSE_PREFIX = "0204"
BROADCAST_PREFIX = "0205"
CONNECTING_PREFIX = "02e0"


@dataclass
class VCMMessage:
    """Represents a parsed VCM protocol message"""
    header: str          # 7 bytes hex
    length: int          # 1 byte
    subheader: str       # 3 bytes hex
    sequence: int        # 1 byte
    data: str            # Variable length hex
    
    @property
    def raw(self) -> str:
        """Reconstruct raw hex payload"""
        return f"{self.header}{self.length:02x}{self.subheader}{self.sequence:02x}{self.data}"
    
    @property
    def raw_bytes(self) -> bytes:
        """Get raw bytes"""
        return bytes.fromhex(self.raw)
    
    @property
    def is_ack(self) -> bool:
        """Check if this is an ACK message"""
        return self.data == ACK_DATA
    
    @property
    def is_request(self) -> bool:
        """Check if this is a request (0200 or 0202)"""
        return self.data.startswith("0200") or self.data.startswith("0202")
    
    @property
    def is_response(self) -> bool:
        """Check if this is a response (0204)"""
        return self.data.startswith("0204")
    
    @property
    def is_broadcast(self) -> bool:
        """Check if this is a status broadcast (0205)"""
        return self.data.startswith("0205")
    
    @property
    def message_type(self) -> str:
        """Get message category from subheader (first 4 chars)"""
        return self.subheader[:4] if len(self.subheader) >= 4 else ""
    
    @property
    def operation(self) -> str:
        """Get operation type from subheader (last 2 chars)"""
        return self.subheader[4:] if len(self.subheader) >= 6 else ""
    
    def __str__(self) -> str:
        msg_type = "ACK" if self.is_ack else ("REQ" if self.is_request else ("RSP" if self.is_response else "BRD"))
        return f"VCMMessage(sub={self.subheader}, seq={self.sequence:02x}, type={msg_type}, data={self.data})"


def parse_message(payload_hex: str) -> Optional[VCMMessage]:
    """
    Parse a hex payload string into a VCMMessage.
    
    Structure:
    - Header: 7 bytes (14 hex chars)
    - Length: 1 byte (2 hex chars)
    - Subheader: 3 bytes (6 hex chars)
    - Sequence: 1 byte (2 hex chars)
    - Data: Variable (remaining)
    """
    if len(payload_hex) < 24:  # Minimum: 14 + 2 + 6 + 2 = 24
        return None
    
    try:
        header = payload_hex[:14]
        length = int(payload_hex[14:16], 16)
        subheader = payload_hex[16:22]
        sequence = int(payload_hex[22:24], 16)
        data = payload_hex[24:]
        
        return VCMMessage(
            header=header,
            length=length,
            subheader=subheader,
            sequence=sequence,
            data=data
        )
    except (ValueError, IndexError):
        return None


def create_message(header: str, subheader: str, sequence: int, data: str) -> VCMMessage:
    """
    Create a new VCM message with correct length calculation.
    
    Length = len(subheader + sequence + data) in bytes
    """
    # Calculate length: subheader(3) + sequence(1) + data(len/2)
    data_len = len(data) // 2 if data else 0
    length = 3 + 1 + data_len
    
    return VCMMessage(
        header=header,
        length=length,
        subheader=subheader,
        sequence=sequence,
        data=data
    )


def create_ack(original: VCMMessage) -> VCMMessage:
    """Create an ACK for an incoming message"""
    return create_message(
        header=original.header,
        subheader=original.subheader,
        sequence=original.sequence,
        data=ACK_DATA
    )


def create_response(original: VCMMessage, response_data: str) -> VCMMessage:
    """
    Create a response message based on an original request.
    Uses same header, subheader, and sequence.
    """
    return create_message(
        header=original.header,
        subheader=original.subheader,
        sequence=original.sequence,
        data=response_data
    )


def create_broadcast(header: str, subheader: str, data: str) -> VCMMessage:
    """Create a broadcast/status message (sequence = 0)"""
    return create_message(
        header=header,
        subheader=subheader,
        sequence=0,
        data=data
    )


def create_request_to_ihu(header: str, subheader: str, sequence: int, data: str) -> VCMMessage:
    """Create a request message from VCM to IHU"""
    return create_message(
        header=header,
        subheader=subheader,
        sequence=sequence,
        data=data
    )


# Header templates observed in packet capture
class Headers:
    """Common header templates"""
    # Format: 00 XX XX YY 000000
    # XX XX seems to be module identifiers
    # YY seems to be a variant
    
    A4_04_0D = "00a4040d000000"  # Module 0x0d related (main)
    A3_03_0F = "00a3030f000000"  # Module 0x0f related
    A4_04_00 = "00a4040000000000"[:14]  # Different format - use first 7 bytes
    A3_03_08 = "00a3030800000000"[:14]
    A3_03_0A = "00a3030a00000000"[:14]
    A3_03_11 = "00a3031100000000"[:14]
    A3_03_10 = "00a3031000000000"[:14]
    A4_04_08 = "00a4040800000000"[:14]
    A4_04_02 = "00a4040200000000"[:14]
    AA_0A_01 = "00aa0a0100000000"[:14]
    AA_0A_07 = "00aa0a0700000000"[:14]
    AB_0B_01 = "00ab0b0100000000"[:14]


# Subheader definitions
class Subheaders:
    """Known subheaders and their meanings"""
    # Handshake/ping
    PING_0D = "a40d00"  # Module 0d status check
    PING_0F = "a30f00"  # Module 0f status check
    
    # Setup sequence
    SETUP_TRIGGER = "a40002"  # Triggers setup sequence
    SETUP_11 = "a31102"       # Setup sub-request 1
    SETUP_10 = "a31002"       # Setup sub-request 2  
    SETUP_08 = "a30802"       # Setup sub-request 3 + connection complete
    
    # Status broadcasts
    STATUS_0A = "a30a05"      # General status
    STATUS_00 = "a40005"      # Setup status
    
    # WiFi scanning
    WIFI_SCAN = "a40d05"      # SSID broadcast
    
    # WiFi connection
    WIFI_PASSWORD = "a40802"  # Password entry
    WIFI_STATUS = "a40805"    # WiFi connection status
    WIFI_FINAL = "a40205"     # Final connection status
    
    # Connection info
    CONN_AA01 = "aa0105"
    CONN_AA07 = "aa0705"
    CONN_AB01 = "ab0105"


# Pre-defined messages for common operations
class StandardMessages:
    """Standard message data patterns"""
    # Request patterns
    REQUEST_BASIC = "02000000"
    REQUEST_20 = "0202000020"
    REQUEST_80 = "0202000080"
    REQUEST_00 = "0202000000"
    
    # Response patterns
    RESPONSE_00 = "020400000000"
    RESPONSE_SHORT = "0204000000"
    RESPONSE_20 = "0204000020"
    RESPONSE_80 = "0204000080"
    
    # Broadcast patterns
    BROADCAST_00 = "0205000000"
    BROADCAST_20 = "0205000020"
    BROADCAST_40 = "0205000040"
    BROADCAST_80 = "0205000080"
    
    # WiFi connection
    WIFI_CONNECTING = "02e0000048"
    
    # SSID data (from capture)
    SSID_SCANNING = "0205000000833a32b9ba30b9baa0"
    SSID_CONNECTED = "0205000040a33a32b9ba30b9b8b0"


def decode_wifi_password_message(msg: VCMMessage) -> Tuple[Optional[str], Optional[bytes]]:
    """
    Decode WiFi password from IHU message.
    Format: 0202000008 + length_byte + ssid/password + extra_data
    Returns (ssid_or_password, extra_bytes)
    """
    if not msg.data.startswith("02020000"):
        return None, None
    
    try:
        # Skip 02020000 (4 bytes = 8 hex chars)
        data_hex = msg.data[8:]
        data_bytes = bytes.fromhex(data_hex)
        
        if len(data_bytes) < 1:
            return None, None
        
        str_len = data_bytes[0]
        if len(data_bytes) < 1 + str_len:
            return None, None
        
        ssid_password = data_bytes[1:1+str_len].decode('utf-8', errors='replace')
        extra = data_bytes[1+str_len:] if len(data_bytes) > 1+str_len else None
        
        return ssid_password, extra
    except:
        return None, None


def encode_wifi_status(connected: bool, ssid_data: str = "a33a32b9ba30b9b8b0") -> str:
    """
    Encode WiFi status broadcast data.
    connected: True for connected (0x40), False for scanning (0x00)
    """
    status_byte = "40" if connected else "00"
    return f"020500{status_byte}{ssid_data}"
