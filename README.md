# VCM Simulator v2

A state-machine based Volvo VCM (Vehicle Connectivity Module) simulator that replicates real VCM behavior for WiFi enable/connect sequences.

>**⚠️ Important Disclaimer**: This is a simplified simulator for testing and development purposes only. The real Volvo VCM is a multi-purpose, complex module with extensive functionality beyond WiFi connectivity. This implementation focuses solely on WiFi-related protocol behavior and should **not** be considered representative of the actual device's complete implementation, architecture, or capabilities.

## Overview

This simulator implements the VCM-IHU (Infotainment Head Unit) UDP communication protocol for WiFi enable operations. The simulator implements the VCM protocol as a finite state machine with the following states:

```
IDLE → HANDSHAKE → SETUP → WIFI_SCANNING → WIFI_CONNECTING → WIFI_CONNECTED
```

## Quick Start

### Network Requirements

The device running this simulator must be configured with:
- **IP Address**: `198.18.32.1`
- **Subnet Mask**: `255.255.0.0`
- **Gateway**: The device should act as the **internet gateway** for the network
- **DNS Server**: The device should provide **DNS resolution** services

### Running the Simulator

```bash
cd vcm_simulator_v2

# Run with default settings (binds to 0.0.0.0:50000)
python3 vcm_simulator.py

# Or specify bind address and port
python3 vcm_simulator.py 127.0.0.1 50000
```

**Important**: The simulator does not implement VCM existence broadcasting. For full functionality, you should also run the VCM liveness broadcaster in a separate terminal:

```bash
# In a separate terminal, run the liveness broadcaster
python3 vcm_liveness.py
```

This will send periodic VCM existence packets that the IHU expects.

**Known Issues:**
- **TLS & Date/Time**: All IHU communication uses TLS. For internet access, the IHU requires correct date/time, but the mechanism for VCM to set IHU datetime is currently unknown.
- **SSID Not Showing**: If SSID `testas` doesn't appear on IHU, restart the simulator, exit the WiFi menu on IHU, and try again.

### Testing with IHU Client

In a separate terminal:

```bash
# Connect to local simulator
python3 test_ihu_client.py 127.0.0.1 50000

# Interactive commands:
IHU> ping      # Send handshake pings
IHU> setup     # Trigger setup sequence
IHU> wifi      # Send WiFi password (uses "laikinas")
IHU> replay    # Replay full captured sequence
IHU> quit      # Exit
```

### Running Tests

```bash
python3 test_vcm.py
```

## Protocol Structure

### Message Format

```
| Header (7 bytes) | Length (1 byte) | Subheader (3 bytes) | Sequence (1 byte) | Data (variable) |
```

Example: `00a4040d00000008a40d002802000000`
- Header: `00a4040d000000`
- Length: `08`
- Subheader: `a40d00`
- Sequence: `28`
- Data: `02000000`

### Key Subheaders

| Subheader | Description |
|-----------|-------------|
| `a40d00` | Module 0x0d ping/status |
| `a30f00` | Module 0x0f ping/status |
| `a40002` | Setup trigger |
| `a40d05` | SSID broadcast |
| `a40802` | WiFi password |
| `a30802` | Setup completion |

### Data Patterns

| Pattern | Meaning |
|---------|---------|
| `02000000` | Request |
| `0202....` | Command with data |
| `020400....` | Response |
| `0205....` | Status broadcast |
| `02700000` | ACK |

### Status Flags (in broadcasts)

| Flag | Meaning |
|------|---------|
| `00` | Not connected / Initial |
| `40` | Connected |
| `80` | In progress / Processing |

## State Machine Details

### State Transitions

1. **IDLE → HANDSHAKE**: After receiving ping messages (a40d00, a30f00)
2. **HANDSHAKE → SETUP**: When receiving setup trigger (a40002 with `0202000020`)
3. **SETUP → WIFI_SCANNING**: After completing setup sequence
4. **WIFI_SCANNING → WIFI_CONNECTING**: When receiving WiFi password
5. **WIFI_CONNECTING → WIFI_CONNECTED**: After IHU confirms connection

### Setup Sequence

When triggered, VCM initiates a burst of requests to IHU:
1. VCM sends `a31102` request → IHU responds with `0204000000`
2. VCM sends `a31002` request → IHU responds with `0204000000`
3. VCM sends `a30802` request → IHU responds with `0204000000`
4. VCM sends status broadcasts (`a30a05`, `a40005`)
5. VCM sends `a30802` with flag 80 → IHU responds
6. VCM sends completion message

### Periodic Broadcasts

In WIFI_SCANNING and WIFI_CONNECTED states, VCM broadcasts SSID status every 5 seconds:

- **Scanning**: `a40d05` with data `0205000000833a32b9ba30b9baa0`
- **Connected**: `a40d05` with data `0205000040a33a32b9ba30b9b8b0`

## ACK Protocol

**Critical**: Every non-ACK message must be acknowledged.

- ACK uses same header, subheader, and sequence as original
- ACK data is always `02700000`
- **Never respond to ACK messages** (prevents infinite loops)

## Network Configuration

| Device | IP | Port |
|--------|-----|------|
| VCM | 198.18.32.1 | 50000 |
| IHU | 198.18.34.1 | 50000 |

For local testing, the simulator binds to `0.0.0.0:50000`.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      vcm_simulator.py                        │
│  ┌─────────────────┐    ┌────────────────────────────────┐  │
│  │   UDP Server    │────│    VCMStateMachine             │  │
│  │  (VCMProtocol)  │    │  ┌──────────────────────────┐  │  │
│  │                 │    │  │ IDLE                      │  │  │
│  │  - Receive      │    │  │   ↓                       │  │  │
│  │  - Send         │    │  │ HANDSHAKE                 │  │  │
│  │  - ACK handling │    │  │   ↓                       │  │  │
│  └─────────────────┘    │  │ SETUP (VCM-initiated)     │  │  │
│                         │  │   ↓                       │  │  │
│                         │  │ WIFI_SCANNING (5s bcast)  │  │  │
│                         │  │   ↓                       │  │  │
│                         │  │ WIFI_CONNECTING           │  │  │
│                         │  │   ↓                       │  │  │
│                         │  │ WIFI_CONNECTED (5s bcast) │  │  │
│                         │  └──────────────────────────┘  │  │
│                         └────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                      vcm_protocol.py                         │
│  - Message parsing/creation                                  │
│  - Header/Subheader constants                                │
│  - ACK generation                                            │
│  - WiFi password decoding                                    │
└──────────────────────────────────────────────────────────────┘
```

## Extending the Simulator

### Adding New Message Handlers

1. Add new subheader constant in `vcm_protocol.py`
2. Add handler in appropriate state method in `vcm_state_machine.py`
3. Add tests in `test_vcm.py`

### Adding New States

1. Add state to `VCMState` enum
2. Create handler method `_handle_<state_name>`
3. Register in `_state_handlers` dict
4. Implement transition logic

## Known Limitations

- SSID data is hardcoded from capture (not dynamically generated)
- No disconnect/reconnect handling implemented
- No error state handling
- Timing between VCM-initiated messages in SETUP is instantaneous (real device has ~50ms gaps)

## Files

| File | Description |
|------|-------------|
| `vcm_protocol.py` | Protocol definitions, message parsing/creation utilities |
| `vcm_state_machine.py` | Core state machine implementation |
| `vcm_simulator.py` | UDP server that runs the VCM simulator |
| `vcm_liveness.py` | VCM existence broadcaster |
| `test_vcm.py` | Comprehensive test suite |
| `test_ihu_client.py` | IHU client for interactive testing |
| `analyze_protocol.py` | Protocol analysis tool |
| `ANALYSIS_REPORT.md` | Detailed protocol documentation |

## References

- Analysis report: `ANALYSIS_REPORT.md`
