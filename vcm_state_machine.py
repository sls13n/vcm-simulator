#!/usr/bin/env python3
"""
VCM State Machine - Core state management and transitions
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Callable, Optional, Dict, Any
import time
import logging

from vcm_protocol import (
    VCMMessage, parse_message, create_ack, create_message, create_response,
    create_broadcast, create_request_to_ihu,
    Headers, Subheaders, StandardMessages,
    decode_wifi_password_message, encode_wifi_status
)

logger = logging.getLogger(__name__)


class VCMState(Enum):
    """VCM operational states"""
    IDLE = auto()           # Initial state, waiting for IHU
    HANDSHAKE = auto()      # Responding to ping messages
    SETUP = auto()          # Complex setup sequence
    WIFI_SCANNING = auto()  # Broadcasting SSID scan results
    WIFI_CONNECTING = auto()  # Processing WiFi password
    WIFI_CONNECTED = auto()   # Connected, broadcasting status


@dataclass
class VCMContext:
    """Shared context for state machine"""
    state: VCMState = VCMState.IDLE
    
    # Sequence tracking
    last_ihu_sequence: int = 0
    next_vcm_sequence: int = 0x50  # VCM-initiated sequences start around 0x50
    
    # Setup sequence tracking
    setup_sequence: int = 0
    setup_trigger_msg: Optional[VCMMessage] = None
    
    # WiFi state
    wifi_ssid: str = "testas"  # SSID name
    wifi_password: str = ""
    wifi_connected: bool = False
    
    # Timing
    last_broadcast_time: float = 0
    broadcast_interval: float = 5.0
    
    # Pending responses (for multi-message sequences)
    pending_responses: List[VCMMessage] = field(default_factory=list)
    
    # Message send callback (set by simulator)
    send_callback: Optional[Callable[[VCMMessage], None]] = None
    
    def get_next_sequence(self) -> int:
        """Get next VCM-initiated sequence number"""
        seq = self.next_vcm_sequence
        self.next_vcm_sequence = (self.next_vcm_sequence + 1) % 256
        return seq


class VCMStateMachine:
    """
    VCM State Machine implementation.
    
    Handles state transitions and message processing for VCM simulation.
    """
    
    def __init__(self):
        self.ctx = VCMContext()
        self._state_handlers: Dict[VCMState, Callable] = {
            VCMState.IDLE: self._handle_idle,
            VCMState.HANDSHAKE: self._handle_handshake,
            VCMState.SETUP: self._handle_setup,
            VCMState.WIFI_SCANNING: self._handle_wifi_scanning,
            VCMState.WIFI_CONNECTING: self._handle_wifi_connecting,
            VCMState.WIFI_CONNECTED: self._handle_wifi_connected,
        }
        
        # Track handshake completion
        self._handshake_count = 0
        self._handshake_messages_seen = set()
        
        # Setup phase tracking
        self._setup_phase = 0
        self._awaiting_ihu_response = False
        
    def set_send_callback(self, callback: Callable[[VCMMessage], None]):
        """Set the callback for sending messages"""
        self.ctx.send_callback = callback
        
    def _send(self, msg: VCMMessage):
        """Send a message via callback"""
        if self.ctx.send_callback:
            logger.info(f"VCM SEND: {msg}")
            self.ctx.send_callback(msg)
        else:
            logger.warning(f"No send callback set, dropping: {msg}")
            
    def process_message(self, payload_hex: str) -> List[VCMMessage]:
        """
        Process an incoming message and return responses.
        
        Returns list of messages to send (may be empty for ACKs).
        """
        msg = parse_message(payload_hex)
        if not msg:
            logger.warning(f"Failed to parse message: {payload_hex}")
            return []
        
        logger.info(f"VCM RECV: {msg} (state={self.ctx.state.name})")
        
        # CRITICAL: Never respond to ACKs
        if msg.is_ack:
            logger.debug(f"Received ACK, not responding")
            return []
        
        # Track sequence numbers from IHU
        if msg.sequence != 0:
            self.ctx.last_ihu_sequence = msg.sequence
        
        # Get handler for current state
        handler = self._state_handlers.get(self.ctx.state)
        if handler:
            responses = handler(msg)
            return responses if responses else []
        
        return []
    
    def tick(self) -> List[VCMMessage]:
        """
        Called periodically to handle timed events (broadcasts).
        Returns messages to send.
        """
        responses = []
        current_time = time.time()
        
        # Handle periodic broadcasts based on state
        if self.ctx.state in (VCMState.WIFI_SCANNING, VCMState.WIFI_CONNECTED):
            if current_time - self.ctx.last_broadcast_time >= self.ctx.broadcast_interval:
                self.ctx.last_broadcast_time = current_time
                broadcast = self._create_ssid_broadcast()
                if broadcast:
                    responses.append(broadcast)
        
        return responses
    
    def _create_ssid_broadcast(self) -> Optional[VCMMessage]:
        """Create SSID broadcast message based on connection state"""
        if self.ctx.state == VCMState.WIFI_SCANNING:
            # Scanning - not connected
            return create_message(
                header=Headers.A4_04_0D,
                subheader=Subheaders.WIFI_SCAN,
                sequence=0,
                data=StandardMessages.SSID_SCANNING
            )
        elif self.ctx.state == VCMState.WIFI_CONNECTED:
            # Connected
            return create_message(
                header=Headers.A4_04_0D,
                subheader=Subheaders.WIFI_SCAN,
                sequence=0,
                data=StandardMessages.SSID_CONNECTED
            )
        return None
    
    # ==================== State Handlers ====================
    
    def _handle_idle(self, msg: VCMMessage) -> List[VCMMessage]:
        """Handle messages in IDLE state"""
        responses = []
        
        # Respond to handshake pings
        if msg.subheader in (Subheaders.PING_0D, Subheaders.PING_0F):
            # Send ACK first
            responses.append(create_ack(msg))
            
            # Send response with status
            if msg.subheader == Subheaders.PING_0D:
                responses.append(create_response(msg, StandardMessages.RESPONSE_00))
            else:
                responses.append(create_response(msg, StandardMessages.RESPONSE_SHORT))
            
            # Track handshake progress
            self._handshake_messages_seen.add(msg.subheader)
            self._handshake_count += 1
            
            # After seeing both types twice, transition to HANDSHAKE
            if len(self._handshake_messages_seen) >= 2 and self._handshake_count >= 2:
                logger.info("Handshake detected, transitioning to HANDSHAKE state")
                self.ctx.state = VCMState.HANDSHAKE
        
        return responses
    
    def _handle_handshake(self, msg: VCMMessage) -> List[VCMMessage]:
        """Handle messages in HANDSHAKE state"""
        responses = []
        
        # Continue responding to pings
        if msg.subheader in (Subheaders.PING_0D, Subheaders.PING_0F):
            responses.append(create_ack(msg))
            if msg.subheader == Subheaders.PING_0D:
                responses.append(create_response(msg, StandardMessages.RESPONSE_00))
            else:
                responses.append(create_response(msg, StandardMessages.RESPONSE_SHORT))
        
        # Setup trigger: a40002 with 0202000020
        elif msg.subheader == Subheaders.SETUP_TRIGGER and msg.data == StandardMessages.REQUEST_20:
            logger.info("Setup sequence triggered!")
            responses.append(create_ack(msg))
            
            # Store for later completion
            self.ctx.setup_trigger_msg = msg
            self.ctx.setup_sequence = msg.sequence
            
            # Transition to SETUP and initiate VCM's setup requests
            self.ctx.state = VCMState.SETUP
            self._setup_phase = 0
            
            # Start the setup sequence - VCM sends requests to IHU
            setup_msgs = self._initiate_setup_sequence()
            responses.extend(setup_msgs)
        
        return responses
    
    def _handle_setup(self, msg: VCMMessage) -> List[VCMMessage]:
        """Handle messages in SETUP state - complex multi-step sequence"""
        responses = []
        
        # Handle IHU responses to our setup requests
        if msg.is_response:
            responses.append(create_ack(msg))
            
            # Progress through setup phases
            if msg.subheader == Subheaders.SETUP_11:
                # IHU responded to a31102, send next: a31002
                self._setup_phase = 1
                responses.extend(self._send_setup_phase(1))
                
            elif msg.subheader == Subheaders.SETUP_10:
                # IHU responded to a31002, send next: a30802
                self._setup_phase = 2
                responses.extend(self._send_setup_phase(2))
                
            elif msg.subheader == Subheaders.SETUP_08:
                # IHU responded to a30802
                if self._setup_phase == 2:
                    # First a30802 response - send broadcasts and another a30802
                    self._setup_phase = 3
                    responses.extend(self._send_setup_phase(3))
                elif self._setup_phase == 3:
                    # Second a30802 response - complete setup
                    self._setup_phase = 4
                    responses.extend(self._complete_setup())
        
        return responses
    
    def _initiate_setup_sequence(self) -> List[VCMMessage]:
        """Start the VCM-initiated setup sequence"""
        responses = []
        
        # First request: a31102 with sequence 0x50
        seq = self.ctx.get_next_sequence()
        msg = create_request_to_ihu(
            header="00a3031100000000"[:14],
            subheader=Subheaders.SETUP_11,
            sequence=seq,
            data=StandardMessages.REQUEST_00
        )
        responses.append(msg)
        
        return responses
    
    def _send_setup_phase(self, phase: int) -> List[VCMMessage]:
        """Send messages for a specific setup phase"""
        responses = []
        seq = self.ctx.get_next_sequence()
        
        if phase == 1:
            # Send a31002 request
            msg = create_request_to_ihu(
                header="00a3031000000000"[:14],
                subheader=Subheaders.SETUP_10,
                sequence=seq,
                data=StandardMessages.REQUEST_00
            )
            responses.append(msg)
            
        elif phase == 2:
            # Send first a30802 request
            msg = create_request_to_ihu(
                header=Headers.A3_03_08,
                subheader=Subheaders.SETUP_08,
                sequence=seq,
                data=StandardMessages.REQUEST_00
            )
            responses.append(msg)
            
        elif phase == 3:
            # Send status broadcasts
            responses.append(create_broadcast(
                header=Headers.A3_03_0A,
                subheader=Subheaders.STATUS_0A,
                data=StandardMessages.BROADCAST_00
            ))
            responses.append(create_broadcast(
                header="00a4040000000000"[:14],
                subheader=Subheaders.STATUS_00,
                data=StandardMessages.BROADCAST_20
            ))
            
            # Send second a30802 request (with flag 80)
            seq = self.ctx.get_next_sequence()
            msg = create_request_to_ihu(
                header=Headers.A3_03_08,
                subheader=Subheaders.SETUP_08,
                sequence=seq,
                data=StandardMessages.REQUEST_80
            )
            responses.append(msg)
        
        return responses
    
    def _complete_setup(self) -> List[VCMMessage]:
        """Complete the setup sequence and transition to scanning"""
        responses = []
        
        # Send another status broadcast
        responses.append(create_broadcast(
            header="00a4040000000000"[:14],
            subheader=Subheaders.STATUS_00,
            data=StandardMessages.BROADCAST_20
        ))
        
        # Send completion response for original setup trigger
        if self.ctx.setup_trigger_msg:
            completion = create_response(
                self.ctx.setup_trigger_msg,
                StandardMessages.RESPONSE_20
            )
            responses.append(completion)
        
        # Transition to WiFi scanning
        logger.info("Setup complete, transitioning to WIFI_SCANNING")
        self.ctx.state = VCMState.WIFI_SCANNING
        self.ctx.last_broadcast_time = time.time()  # Start broadcast timer
        
        return responses
    
    def _handle_wifi_scanning(self, msg: VCMMessage) -> List[VCMMessage]:
        """Handle messages in WIFI_SCANNING state"""
        responses = []
        
        # Handle pings (keep-alive)
        if msg.subheader in (Subheaders.PING_0D, Subheaders.PING_0F):
            responses.append(create_ack(msg))
            if msg.subheader == Subheaders.PING_0D:
                responses.append(create_response(msg, StandardMessages.RESPONSE_00))
            else:
                responses.append(create_response(msg, StandardMessages.RESPONSE_SHORT))
        
        # WiFi password received
        elif msg.subheader == Subheaders.WIFI_PASSWORD and msg.is_request:
            logger.info("WiFi password received, transitioning to WIFI_CONNECTING")
            responses.append(create_ack(msg))
            
            # Decode password
            password, extra = decode_wifi_password_message(msg)
            if password:
                logger.info(f"WiFi password decoded: {password}")
                self.ctx.wifi_password = password
            
            # Store sequence for responses
            self._wifi_connect_sequence = msg.sequence
            
            # Transition and start connection sequence
            self.ctx.state = VCMState.WIFI_CONNECTING
            responses.extend(self._start_wifi_connection(msg))
        
        return responses
    
    def _start_wifi_connection(self, password_msg: VCMMessage) -> List[VCMMessage]:
        """Start the WiFi connection sequence"""
        responses = []
        
        # Send connecting status: 02e0000048
        responses.append(create_response(password_msg, StandardMessages.WIFI_CONNECTING))
        
        # Send status update: a30a05 with flag 80
        responses.append(create_broadcast(
            header=Headers.A3_03_0A,
            subheader=Subheaders.STATUS_0A,
            data=StandardMessages.BROADCAST_80
        ))
        
        # Send password accepted response with connection data
        responses.append(create_message(
            header=Headers.A4_04_08,
            subheader=Subheaders.WIFI_PASSWORD,
            sequence=password_msg.sequence,
            data="020400000ce8cae6e8c2e680"  # From capture
        ))
        
        # Send connection info messages
        responses.append(create_broadcast(
            header=Headers.AA_0A_01,
            subheader=Subheaders.CONN_AA01,
            data=StandardMessages.BROADCAST_40
        ))
        responses.append(create_broadcast(
            header=Headers.AA_0A_07,
            subheader=Subheaders.CONN_AA07,
            data=StandardMessages.BROADCAST_40
        ))
        responses.append(create_broadcast(
            header=Headers.AB_0B_01,
            subheader=Subheaders.CONN_AB01,
            data=StandardMessages.BROADCAST_00
        ))
        
        # Send WiFi status
        responses.append(create_broadcast(
            header=Headers.A4_04_08,
            subheader=Subheaders.WIFI_STATUS,
            data="020500000ce8cae6e8c2e680"  # From capture
        ))
        
        # Send connection complete request (VCM asks IHU to confirm)
        seq = self.ctx.get_next_sequence()
        self._connection_complete_seq = seq
        responses.append(create_request_to_ihu(
            header=Headers.A3_03_08,
            subheader=Subheaders.SETUP_08,
            sequence=seq,
            data=StandardMessages.REQUEST_80
        ))
        
        return responses
    
    def _handle_wifi_connecting(self, msg: VCMMessage) -> List[VCMMessage]:
        """Handle messages in WIFI_CONNECTING state"""
        responses = []
        
        # Wait for IHU confirmation of connection complete (a30802 response)
        if msg.subheader == Subheaders.SETUP_08 and msg.is_response:
            responses.append(create_ack(msg))
            
            # Send final status
            responses.append(create_broadcast(
                header=Headers.A4_04_02,
                subheader=Subheaders.WIFI_FINAL,
                data="020500001a"  # From capture
            ))
            
            # Transition to connected
            logger.info("WiFi connection confirmed, transitioning to WIFI_CONNECTED")
            self.ctx.state = VCMState.WIFI_CONNECTED
            self.ctx.wifi_connected = True
            self.ctx.last_broadcast_time = time.time()
        
        return responses
    
    def _handle_wifi_connected(self, msg: VCMMessage) -> List[VCMMessage]:
        """Handle messages in WIFI_CONNECTED state"""
        responses = []
        
        # Handle pings
        if msg.subheader in (Subheaders.PING_0D, Subheaders.PING_0F):
            responses.append(create_ack(msg))
            if msg.subheader == Subheaders.PING_0D:
                responses.append(create_response(msg, StandardMessages.RESPONSE_00))
            else:
                responses.append(create_response(msg, StandardMessages.RESPONSE_SHORT))
        
        # Could add disconnect handling here
        
        return responses


def create_vcm_state_machine() -> VCMStateMachine:
    """Factory function to create a configured VCM state machine"""
    return VCMStateMachine()
