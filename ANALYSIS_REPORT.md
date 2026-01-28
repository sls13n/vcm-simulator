# VCM Protocol Analysis Report

## Protocol Structure

The VCM protocol uses the following message structure:

| Field | Size | Example | Notes |
|-------|------|---------|-------|
| Header | 7 bytes | `00a4040d000000` | Contains module identifiers |
| Length | 1 byte | `08` or `12` | Length of remaining payload |
| Subheader | 3 bytes | `a40d05` | Message type identifier |
| Sequence | 1 byte | `28` | Sequence number (00 if not used) |
| Data | Variable | `020500004...` | Command/response data |

### Key Discovery: Subheader Structure
The subheader appears to encode:
- **Byte 1-2**: Message category/module (e.g., `a40d`, `a30f`, `a408`)
- **Byte 3**: Operation type (`00`=request, `02`=command, `05`=status/broadcast)

## Communication Patterns

### 1. ACK Pattern
Every non-ACK message receives an acknowledgment with data `02700000`:
```
IHU->VCM: 00a4040d00000008a40d002802000000  (command)
VCM->IHU: 00a4040d00000008a40d002802700000  (ACK - note same subheader & seq)
```
**CRITICAL**: ACKs maintain same subheader and sequence number as the original message.

### 2. Request-Response Pattern
```
IHU sends request:  data ends with 02000000 or 0202000000
VCM sends response: data ends with 020400000000 or 0204000000
```
The `02` prefix seems to indicate message type, `00` = request, `04` = response, `70` = ACK.

### 3. Broadcast/Status Pattern
Messages with subheader ending in `05` (e.g., `a40d05`, `a30a05`) are status broadcasts:
- Sequence is always `00`
- Data starts with `0205` (status indicator)

## State Machine Analysis

### Identified States

```
┌─────────────────────────────────────────────────────────────────┐
│                    VCM STATE MACHINE                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    IHU ping (a40d00/a30f00)    ┌──────────┐       │
│  │   IDLE   │ ─────────────────────────────> │ HANDSHAKE │       │
│  └──────────┘                                 └──────────┘       │
│       │                                            │             │
│       │                                            │ Complete    │
│       │                                            ▼             │
│       │    ┌─────────────────────────────────────────────────┐   │
│       │    │              SETUP SEQUENCE                      │   │
│       │    │  Triggered by: a40002 seq=32 (0202000020)       │   │
│       │    │  VCM sends: a31102, a31002, a30802 requests     │   │
│       │    │  IHU responds to each with 0204... response     │   │
│       │    │  VCM sends: a30a05, a40005 status broadcasts    │   │
│       │    │  VCM ends with: a40002 (0204000020)             │   │
│       │    └─────────────────────────────────────────────────┘   │
│                                     │                            │
│                                     ▼                            │
│       ┌─────────────────────────────────────────────────────┐   │
│       │           WIFI_SCANNING                              │   │
│       │  Periodic broadcast every 5s:                        │   │
│       │  a40d05 seq=00 data=0205000000833a32b9ba30b9baa0    │   │
│       │  (SSID scan results, status=00 not connected)        │   │
│       └─────────────────────────────────────────────────────┘   │
│                                     │                            │
│                                     │ IHU sends password         │
│                                     │ a40802 (02020000...)       │
│                                     ▼                            │
│       ┌─────────────────────────────────────────────────────┐   │
│       │           WIFI_CONNECTING                            │   │
│       │  VCM sends: 02e0000048 (connecting status)           │   │
│       │  VCM sends: a30a05 (0205000080) - status update      │   │
│       │  VCM sends: a40802 (020400...) - password response   │   │
│       │  VCM sends: aa0105, aa0705, ab0105 - connection info │   │
│       │  VCM sends: a40805 - final wifi status               │   │
│       │  VCM sends: a30802 (0202000080) - completion signal  │   │
│       │  IHU responds: a30802 (0204000080)                   │   │
│       │  VCM sends: a40205 (020500001a) - final status       │   │
│       └─────────────────────────────────────────────────────┘   │
│                                     │                            │
│                                     ▼                            │
│       ┌─────────────────────────────────────────────────────┐   │
│       │           WIFI_CONNECTED                             │   │
│       │  Periodic broadcast every 5s:                        │   │
│       │  a40d05 seq=00 data=0205000040a33a32b9ba30b9b8b0    │   │
│       │  (SSID info, status=40 connected)                    │   │
│       └─────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Detailed Phase Analysis

### Phase 1: Initial Handshake
**Duration**: ~6 seconds

Two types of ping messages, repeated twice:
1. `a40d00` - Module 0x0d status request
2. `a30f00` - Module 0x0f status request

**Pattern**:
```
IHU->VCM: a40d00 seq=28 data=02000000  (request)
VCM->IHU: a40d00 seq=28 data=02700000  (ACK)
VCM->IHU: a40d00 seq=28 data=020400000000  (response)
IHU->VCM: a40d00 seq=28 data=02700000  (ACK for response)
```

### Phase 2: Setup Sequence
**Duration**: ~280ms

**Trigger**: IHU sends `a40002` with `0202000020`

**VCM responds with a burst of messages**:
1. `a31102` seq=50 - request to IHU, IHU responds with `0204000000`
2. `a31002` seq=51 - request to IHU, IHU responds with `0204000000`  
3. `a30802` seq=52 - request to IHU, IHU responds with `0204000000`
4. `a30a05` seq=00 - status broadcast `0205000000`
5. `a40005` seq=00 - status broadcast `0205000020`
6. `a30802` seq=54 - another request with flag `0202000080`
7. More status messages...

**Ends with**: VCM sends `a40002` seq=32 data=`0204000020` (completing the sequence started by IHU)

**Observation**: This is a complex setup loop where VCM initiates multiple sub-conversations.

### Phase 3: WiFi Scanning
**Duration**: ~20 seconds

VCM broadcasts SSID scan results every 5 seconds:
```
a40d05 seq=00 data=0205000000833a32b9ba30b9baa0
```
- `02050000` - Status broadcast header
- `00` - Connection status (not connected)
- `833a32b9ba30b9baa0` - SSID data (encoded)

### Phase 4: WiFi Connection
**Duration**: ~1 second (VERY FAST!)

**Trigger**: IHU sends password:
```
a40802 seq=4b data=02020000086c61696b696e617319d195cdd185cc
                          ^^"laikinas" (SSID/password)
```

**VCM Connection Sequence**:
1. `a40802` seq=4b data=`02e0000048` - Processing/connecting status
2. `a30a05` seq=00 data=`0205000080` - Status update (80 = in progress?)
3. `a40802` seq=4b data=`020400000ce8cae6e8c2e680` - Password accepted
4. `aa0105` seq=00 data=`0205000040` - Connection info
5. `aa0705` seq=00 data=`0205000040` - Connection info
6. `ab0105` seq=00 data=`0205000000` - Connection info
7. `a40805` seq=00 data=`020500000ce8cae6e8c2e680` - WiFi status
8. `a30802` seq=72 data=`0202000080` - Connection complete request
9. IHU responds: `a30802` seq=72 data=`0204000080`
10. `a40205` seq=00 data=`020500001a` - Final status

### Phase 5: Connected State
**Ongoing**: Periodic broadcasts every 5 seconds

VCM broadcasts connected status every 5 seconds:
```
a40d05 seq=00 data=0205000040a33a32b9ba30b9b8b0
```
- `0205` - Status broadcast
- `0040` - Connection status (40 = connected!)
- `a33a32b9ba30b9b8b0` - Connected SSID info

## ACK Loop Prevention

**CRITICAL**: Never ACK an ACK!

Detection: If `data == "02700000"`, it's an ACK - don't respond.

## Data Encoding Notes

1. SSID "laikinas" appears in password message: `086c61696b696e6173` = length(8) + "laikinas"
2. Status flags observed:
   - `00` = Not connected / Initial
   - `40` = Connected
   - `80` = In progress / Processing
   - `20` = Setup mode (seen in a40002 messages)

## Conclusion

The VCM behaves as a **reactive state machine** with:
- **IHU-triggered state transitions** (handshake, setup, password entry)
- **VCM-initiated message bursts** during setup and connection phases
- **Periodic status broadcasts** during scanning and connected states
- **Strict ACK protocol** with same subheader/sequence echoing

