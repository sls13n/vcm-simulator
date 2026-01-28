#!/usr/bin/env python3
"""
VCM Simulator Test Suite - Validates state machine against captured traffic
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vcm_protocol import (
    parse_message, create_message, create_ack, create_response,
    VCMMessage, ACK_DATA, Headers, Subheaders, StandardMessages,
    decode_wifi_password_message
)
from vcm_state_machine import VCMStateMachine, VCMState


class TestProtocolParsing(unittest.TestCase):
    """Test protocol message parsing"""
    
    def test_parse_basic_message(self):
        """Test parsing a basic message"""
        payload = "00a4040d00000008a40d002802000000"
        msg = parse_message(payload)
        
        self.assertIsNotNone(msg)
        self.assertEqual(msg.header, "00a4040d000000")
        self.assertEqual(msg.length, 0x08)
        self.assertEqual(msg.subheader, "a40d00")
        self.assertEqual(msg.sequence, 0x28)
        self.assertEqual(msg.data, "02000000")
    
    def test_parse_ack_message(self):
        """Test parsing an ACK message"""
        payload = "00a4040d00000008a40d002802700000"
        msg = parse_message(payload)
        
        self.assertIsNotNone(msg)
        self.assertTrue(msg.is_ack)
        self.assertEqual(msg.data, ACK_DATA)
    
    def test_parse_broadcast_message(self):
        """Test parsing a broadcast message"""
        payload = "00a4040d00000012a40d05000205000000833a32b9ba30b9baa0"
        msg = parse_message(payload)
        
        self.assertIsNotNone(msg)
        self.assertEqual(msg.subheader, "a40d05")
        self.assertEqual(msg.sequence, 0)
        self.assertTrue(msg.is_broadcast)
    
    def test_message_reconstruction(self):
        """Test that parsed message can be reconstructed"""
        original = "00a4040d00000008a40d002802000000"
        msg = parse_message(original)
        reconstructed = msg.raw
        
        self.assertEqual(original, reconstructed)
    
    def test_decode_wifi_password(self):
        """Test decoding WiFi password from message"""
        payload = "00a4040800000018a408024b02020000086c61696b696e617319d195cdd185cc"
        msg = parse_message(payload)
        
        password, extra = decode_wifi_password_message(msg)
        self.assertEqual(password, "laikinas")


class TestACKGeneration(unittest.TestCase):
    """Test ACK message generation"""
    
    def test_create_ack(self):
        """Test ACK creation preserves subheader and sequence"""
        original_payload = "00a4040d00000008a40d002802000000"
        original = parse_message(original_payload)
        ack = create_ack(original)
        
        self.assertEqual(ack.subheader, original.subheader)
        self.assertEqual(ack.sequence, original.sequence)
        self.assertEqual(ack.data, ACK_DATA)
        self.assertTrue(ack.is_ack)


class TestStateMachineTransitions(unittest.TestCase):
    """Test state machine state transitions"""
    
    def setUp(self):
        self.sm = VCMStateMachine()
        self.sent_messages = []
        self.sm.set_send_callback(lambda msg: self.sent_messages.append(msg))
    
    def test_initial_state(self):
        """Test initial state is IDLE"""
        self.assertEqual(self.sm.ctx.state, VCMState.IDLE)
    
    def test_handshake_ping_0d(self):
        """Test response to ping 0d (a40d00)"""
        payload = "00a4040d00000008a40d002802000000"
        responses = self.sm.process_message(payload)
        
        # Should get ACK + response
        self.assertEqual(len(responses), 2)
        self.assertTrue(responses[0].is_ack)
        self.assertTrue(responses[1].is_response)
    
    def test_handshake_ping_0f(self):
        """Test response to ping 0f (a30f00)"""
        payload = "00a3030f00000008a30f002902000000"
        responses = self.sm.process_message(payload)
        
        # Should get ACK + response
        self.assertEqual(len(responses), 2)
        self.assertTrue(responses[0].is_ack)
        self.assertTrue(responses[1].is_response)
    
    def test_ack_not_responded(self):
        """Test that ACK messages are not responded to"""
        # First, trigger a normal message to get to a state
        self.sm.process_message("00a4040d00000008a40d002802000000")
        
        # Now send an ACK - should not get response
        ack_payload = "00a4040d00000008a40d002802700000"
        responses = self.sm.process_message(ack_payload)
        
        self.assertEqual(len(responses), 0)
    
    def test_transition_to_handshake(self):
        """Test transition from IDLE to HANDSHAKE"""
        # Send two different ping types
        self.sm.process_message("00a4040d00000008a40d002802000000")  # ping 0d
        self.sm.process_message("00a3030f00000008a30f002902000000")  # ping 0f
        
        # Should be in HANDSHAKE state now
        self.assertEqual(self.sm.ctx.state, VCMState.HANDSHAKE)


class TestCapturedTrafficReplay(unittest.TestCase):
    """Replay captured traffic and verify behavior"""
    
    def setUp(self):
        self.sm = VCMStateMachine()
        self.sent_messages = []
        self.sm.set_send_callback(lambda msg: self.sent_messages.append(msg))
    
    def _send_and_expect_ack(self, payload: str, expect_response: bool = True):
        """Helper to send message and verify ACK is returned"""
        responses = self.sm.process_message(payload)
        if responses:
            # First response should be ACK
            self.assertTrue(responses[0].is_ack, f"Expected ACK, got {responses[0]}")
        return responses
    
    def test_full_wifi_enable_sequence(self):
        """Test the full WiFi enable sequence from captured traffic"""
        
        # Phase 1: Initial handshake
        # Packet 1: IHU ping
        responses = self._send_and_expect_ack("00a4040d00000008a40d002802000000")
        self.assertEqual(self.sm.ctx.state, VCMState.IDLE)
        
        # Packet 5: Second ping type
        responses = self._send_and_expect_ack("00a3030f00000008a30f002902000000")
        self.assertEqual(self.sm.ctx.state, VCMState.HANDSHAKE)
        
        # Packet 9: Another ping (second round)
        responses = self._send_and_expect_ack("00a4040d00000008a40d003002000000")
        
        # Packet 13: Another ping type
        responses = self._send_and_expect_ack("00a3030f00000008a30f003102000000")
        
        # Packet 17: Setup trigger
        responses = self._send_and_expect_ack("00a4040000000009a40002320202000020")
        
        # VCM should initiate setup sequence
        self.assertEqual(self.sm.ctx.state, VCMState.SETUP)
        
        # VCM sends a31102 request, we need to respond
        # Find the a31102 request in responses
        setup_requests = [r for r in responses if r.subheader == "a31102"]
        self.assertTrue(len(setup_requests) > 0, "VCM should send a31102 request")
        
        # Respond to a31102
        a31102_response = "00a3031100000009a31102500204000000"
        responses = self.sm.process_message(a31102_response)
        
        # VCM should send a31002 next
        a31002_requests = [r for r in responses if r.subheader == "a31002"]
        self.assertTrue(len(a31002_requests) > 0, "VCM should send a31002 request")
        
        # Respond to a31002
        a31002_response = "00a3031000000009a31002510204000000"
        responses = self.sm.process_message(a31002_response)
        
        # VCM should send a30802 next
        a30802_requests = [r for r in responses if r.subheader == "a30802"]
        self.assertTrue(len(a30802_requests) > 0, "VCM should send a30802 request")
        
        # Respond to first a30802
        a30802_response1 = "00a3030800000009a30802520204000000"
        responses = self.sm.process_message(a30802_response1)
        
        # Should get broadcasts and another a30802
        a30802_requests_2 = [r for r in responses if r.subheader == "a30802"]
        
        # Respond to second a30802 (with flag 80)
        a30802_response2 = "00a3030800000009a30802540204000080"
        responses = self.sm.process_message(a30802_response2)
        
        # Should transition to WIFI_SCANNING
        self.assertEqual(self.sm.ctx.state, VCMState.WIFI_SCANNING)
        
        print(f"\n✓ Successfully reached WIFI_SCANNING state")
        
        # Test tick generates broadcast
        import time
        self.sm.ctx.last_broadcast_time = time.time() - 10  # Force broadcast
        tick_messages = self.sm.tick()
        self.assertTrue(len(tick_messages) > 0, "Should generate SSID broadcast")
        broadcast = tick_messages[0]
        self.assertEqual(broadcast.subheader, "a40d05")
        
        print(f"✓ SSID broadcast working: {broadcast.data}")
        
        # Test WiFi password entry
        password_msg = "00a4040800000018a408024b02020000086c61696b696e617319d195cdd185cc"
        responses = self.sm.process_message(password_msg)
        
        self.assertEqual(self.sm.ctx.state, VCMState.WIFI_CONNECTING)
        print(f"✓ Transitioned to WIFI_CONNECTING after password")
        
        # Find the a30802 connection complete request from VCM
        a30802_complete = [r for r in responses if r.subheader == "a30802"]
        self.assertTrue(len(a30802_complete) > 0, "VCM should send connection complete request")
        
        # Respond to complete connection
        complete_response = f"00a3030800000009a30802{a30802_complete[0].sequence:02x}0204000080"
        responses = self.sm.process_message(complete_response)
        
        # Should be connected now
        self.assertEqual(self.sm.ctx.state, VCMState.WIFI_CONNECTED)
        self.assertTrue(self.sm.ctx.wifi_connected)
        
        print(f"✓ Successfully reached WIFI_CONNECTED state")
        
        # Test connected broadcast
        self.sm.ctx.last_broadcast_time = time.time() - 10  # Force broadcast
        tick_messages = self.sm.tick()
        self.assertTrue(len(tick_messages) > 0, "Should generate connected broadcast")
        broadcast = tick_messages[0]
        self.assertIn("40", broadcast.data, "Connected broadcast should have status 40")
        
        print(f"✓ Connected broadcast working: {broadcast.data}")
        print(f"\n{'='*60}")
        print(f"ALL TESTS PASSED - VCM Simulator behaves like real device")
        print(f"{'='*60}")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""
    
    def setUp(self):
        self.sm = VCMStateMachine()
        self.sent_messages = []
        self.sm.set_send_callback(lambda msg: self.sent_messages.append(msg))
    
    def test_invalid_payload(self):
        """Test handling of invalid payload"""
        responses = self.sm.process_message("invalid")
        self.assertEqual(len(responses), 0)
    
    def test_short_payload(self):
        """Test handling of too-short payload"""
        responses = self.sm.process_message("00a404")
        self.assertEqual(len(responses), 0)
    
    def test_double_ack_prevention(self):
        """Test that ACKs don't generate ACKs"""
        # Send a normal message first
        self.sm.process_message("00a4040d00000008a40d002802000000")
        
        # Now send multiple ACKs - none should generate responses
        for _ in range(5):
            responses = self.sm.process_message("00a4040d00000008a40d002802700000")
            self.assertEqual(len(responses), 0, "ACK should not generate response")


if __name__ == "__main__":
    # Run tests with verbosity
    unittest.main(verbosity=2)
