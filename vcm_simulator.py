#!/usr/bin/env python3
"""
VCM Simulator v2 - UDP Server for Volvo VCM Simulation

This simulator implements the VCM protocol as a state machine,
accurately replicating real VCM behavior observed in packet captures.
"""

import asyncio
import logging
import sys
import signal
from typing import Optional, Tuple
from datetime import datetime

from vcm_protocol import VCMMessage, parse_message
from vcm_state_machine import VCMStateMachine, VCMState

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Network configuration
VCM_IP = "198.18.32.1"
VCM_PORT = 50000
IHU_IP = "198.18.34.1"
IHU_PORT = 50000

# Timing
TICK_INTERVAL = 0.1  # 100ms tick for periodic events


class VCMProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for VCM simulator"""
    
    def __init__(self, state_machine: VCMStateMachine):
        self.state_machine = state_machine
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.ihu_addr: Optional[Tuple[str, int]] = None
        
        # Register send callback
        self.state_machine.set_send_callback(self._send_message)
    
    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport
        logger.info(f"VCM Simulator listening on {VCM_IP}:{VCM_PORT}")
    
    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming UDP datagrams"""
        # Remember IHU address for responses
        self.ihu_addr = addr
        
        # Convert to hex string for processing
        payload_hex = data.hex()
        
        # Ignore liveness packets - no response needed
        if payload_hex in ("ffffff010000000cff0106140206010003000000", "ffffff010000000cff0106320206010001000000"):
            logger.debug(f"Ignoring liveness packet from {addr}")
            return
        
        logger.debug(f"Received from {addr}: {payload_hex}")
        
        # Process through state machine
        responses = self.state_machine.process_message(payload_hex)
        
        # Send responses
        for response in responses:
            self._send_message(response)
    
    def _send_message(self, msg: VCMMessage):
        """Send a VCM message to IHU"""
        if not self.transport:
            logger.error("Transport not available")
            return
        
        # Default to broadcast if no IHU address known
        target_addr = self.ihu_addr or (IHU_IP, IHU_PORT)
        
        payload_bytes = msg.raw_bytes
        self.transport.sendto(payload_bytes, target_addr)
        logger.debug(f"Sent to {target_addr}: {msg.raw}")
    
    def error_received(self, exc):
        logger.error(f"Error received: {exc}")
    
    def connection_lost(self, exc):
        logger.info("Connection closed")


class VCMSimulator:
    """Main VCM Simulator controller"""
    
    def __init__(self, bind_ip: str = "0.0.0.0", bind_port: int = VCM_PORT):
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.state_machine = VCMStateMachine()
        self.protocol: Optional[VCMProtocol] = None
        self.running = False
        self._tick_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the VCM simulator"""
        logger.info("=" * 60)
        logger.info("VCM Simulator v2 - State Machine Implementation")
        logger.info("=" * 60)
        logger.info(f"VCM IP: {VCM_IP} (simulated)")
        logger.info(f"Binding to: {self.bind_ip}:{self.bind_port}")
        logger.info(f"IHU Expected: {IHU_IP}:{IHU_PORT}")
        logger.info("=" * 60)
        
        # Create UDP endpoint
        loop = asyncio.get_event_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: VCMProtocol(self.state_machine),
            local_addr=(self.bind_ip, self.bind_port)
        )
        
        self.protocol = protocol
        self.running = True
        
        # Start periodic tick task
        self._tick_task = asyncio.create_task(self._tick_loop())
        
        logger.info("VCM Simulator started. Press Ctrl+C to stop.")
        logger.info(f"Current state: {self.state_machine.ctx.state.name}")
    
    async def _tick_loop(self):
        """Periodic tick for broadcasts and timed events"""
        while self.running:
            try:
                # Call state machine tick
                messages = self.state_machine.tick()
                
                # Send any periodic messages
                for msg in messages:
                    if self.protocol:
                        self.protocol._send_message(msg)
                
                # Log state changes
                current_state = self.state_machine.ctx.state
                
                await asyncio.sleep(TICK_INTERVAL)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Tick error: {e}")
    
    async def stop(self):
        """Stop the VCM simulator"""
        logger.info("Stopping VCM Simulator...")
        self.running = False
        
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
        
        if self.protocol and self.protocol.transport:
            self.protocol.transport.close()
        
        logger.info("VCM Simulator stopped.")
    
    def get_status(self) -> dict:
        """Get current simulator status"""
        return {
            "running": self.running,
            "state": self.state_machine.ctx.state.name,
            "wifi_connected": self.state_machine.ctx.wifi_connected,
            "wifi_ssid": self.state_machine.ctx.wifi_ssid,
        }


async def main():
    """Main entry point"""
    # Parse command line args
    bind_ip = "0.0.0.0"
    bind_port = VCM_PORT
    
    if len(sys.argv) > 1:
        bind_ip = sys.argv[1]
    if len(sys.argv) > 2:
        bind_port = int(sys.argv[2])
    
    # Create simulator
    simulator = VCMSimulator(bind_ip, bind_port)
    
    # Setup signal handlers (Unix/Linux/macOS only)
    # Windows doesn't support add_signal_handler, but Ctrl+C works via KeyboardInterrupt
    if sys.platform != 'win32':
        loop = asyncio.get_event_loop()
        
        def signal_handler():
            asyncio.create_task(simulator.stop())
        
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
    
    try:
        await simulator.start()
        
        # Keep running until stopped
        while simulator.running:
            await asyncio.sleep(1)
            
            # Print status periodically
            status = simulator.get_status()
            logger.info(f"Status: state={status['state']}, wifi_connected={status['wifi_connected']}")
            
    except KeyboardInterrupt:
        pass
    finally:
        await simulator.stop()


if __name__ == "__main__":
    asyncio.run(main())
