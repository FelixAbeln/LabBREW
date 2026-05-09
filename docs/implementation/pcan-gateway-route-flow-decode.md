# PCAN Gateway Route Flow Decode (2026-05-09)

## Scope

This document decodes the gateway control-plane and data-plane flow captured in:

- logs/captures/gateway_flow_20260509_111056.pcapng

Goal:

- Explain why behavior changes when PCAN Virtual Gateway software is connected.
- Provide transport-layer requirements for LabBREW implementation.

## Capture Summary

Endpoints observed:

- 192.168.5.37 = PCAN-Ethernet Gateway DR
- 192.168.5.65 = host running PCAN software / test tools

Protocols and ports:

- UDP data plane: 192.168.5.37:34888 -> 192.168.5.65:55001 only
- TCP control plane: port 45321 (both directions, short and long sessions)

Traffic totals:

- UDP: 1702 packets (~132 kB), one-way, continuous
- TCP: repeated short sessions plus one longer authenticated session

## UDP Data-Plane Decode

Observed conversation:

- 192.168.5.37:34888 -> 192.168.5.65:55001

Key properties:

- No reverse UDP from host to gateway in this capture.
- No UDP seen on port 55002.
- UDP length remained stable at 44 bytes in sampled packets.
- Per-second volume remained roughly steady across the full capture.

Interpretation:

- Route bound to UDP 55001 remains active and continuously transmits.
- Data-plane continuity alone does not guarantee agitator actuation behavior.

## TCP Control-Plane Decode

Control channel port:

- 45321

Two distinct flow families are present.

### Family A: Short recurring route announcements (streams 0,1,2,3,4,5,7,8,9,10)

Pattern for each stream:

1. HEJ_REQ (31 bytes)
2. HEJ_CNF (35 bytes)
3. ROUTE_REQ (372 bytes)
4. Session closes quickly

Decoded ROUTE_REQ fields (repeated):

- name="rt1"
- state=0x98000003
- can="can0"
- port=55001
- proto="udp"
- bitrate=1000000

Timing:

- New short session SYN appears every ~3.016 seconds
- Measured deltas: 3.015877, 3.016651, 3.016202, 3.016682, 3.015797, 3.015773, 3.015899, 3.016391, 3.016028 s

Interpretation:

- This is a periodic route heartbeat/announcement for rt1 on UDP 55001.

### Family B: One long authenticated route-management session (stream 6)

Direction and timing:

- Initiator: 192.168.5.65:54029 -> 192.168.5.37:45321
- Starts at ~16.952 s, duration ~5.48 s

Message sequence (decoded):

1. HEJ_REQ pver="2.0.2" uver="1.0.2"
2. HEJ_CNF uver=1.7.2 pver=2.1.1
3. ROUTE_REQ name="rt2" state="0x88000002" port="55002" proto="udp"
4. ROUTE_CNF name="rt2" state=0x18000003 status=0 nonces=...
5. ROUTE_AUTH_REQ rtauth=...
6. ROUTE_AUTH_CNF status=0 noncec=...
7. ROUTE_UPDATE_REQ name="rt2" state=0x18000003 status=0
8. FW_INFO_REQ / FW_INFO_CNF
9. DEV_GET_ID_REQ / DEV_GET_ID_CNF
10. Repeated CAN_INFO_REQ / CAN_INFO_CNF cycles
11. ROUTE_UPDATE_REQ name="rt2" state="0x88000002"
12. ROUTE_UPDATE_CNF status=0

Interpretation:

- PCAN software creates and authenticates a second route context (rt2), distinct from periodic rt1 announcements.
- This session performs active management (auth + route updates + CAN capability checks).

## Behavioral Hypothesis Supported by Capture

What the capture strongly shows:

- LabBREW-relevant UDP stream on 55001 is continuously present.
- PCAN software connection introduces additional authenticated control behavior on rt2 (state transitions and route updates).

Most likely consequence:

- Gateway internal route authorization/state machine is modified by rt2 management traffic.
- Actuation success can depend on this control-plane state, even when UDP packets appear valid.

This matches earlier findings where payload framing/flags were corrected, but behavior still differed by PCAN software connection state.

## Transport-Layer Requirements for LabBREW

To remove dependency on external PCAN software, LabBREW transport should implement control-plane parity, not only UDP frame TX.

### Required capabilities

1. Maintain TCP control channel to gateway control port 45321.
2. Perform handshake negotiation:
   - HEJ_REQ/HEJ_CNF
3. Perform explicit route lifecycle for a dedicated route name (for example rt_labbrew):
   - ROUTE_REQ with desired UDP port/proto/can settings
   - Handle ROUTE_CNF status and accepted state
4. Support route authentication flow if requested:
   - ROUTE_AUTH_REQ/ROUTE_AUTH_CNF
5. Maintain route health:
   - periodic ROUTE_UPDATE_REQ
   - periodic CAN_INFO_REQ checks
6. Reconcile route state transitions:
   - detect and log changes in state bitfield
   - recover route if state degrades
7. Keep UDP sender aligned to the active route parameters negotiated via control plane.

### Retry and resiliency policy

1. If TCP control drops, re-establish and renegotiate route before considering outputs healthy.
2. If UDP path remains up but control state is degraded, mark route as degraded and attempt recovery.
3. Backoff retries with bounded jitter.
4. Expose route-health state to logs and diagnostics API.

### Observability requirements

1. Log each control message type with direction and timestamp.
2. Log route name, state value, and status codes from ROUTE_CNF/ROUTE_UPDATE_CNF.
3. Log CAN_INFO status snapshots and transitions.
4. Correlate UDP TX activity with control-plane route state in one timeline.

## Suggested Implementation Plan

1. Add optional control-plane manager in Services/parameterDB/sourceDefs/brewtools/transports/pcan_gateway.py:
   - manages TCP 45321 session
   - route negotiation/auth/update
2. Keep existing UDP send path for CAN payload transport.
3. Gate "transport healthy" on both:
   - UDP TX success
   - control-plane route state healthy
4. Add feature flag for staged rollout:
   - control_plane_enabled=true/false
5. Add integration test harness using recorded message fixtures and a mock gateway.

## Validation Checklist

After implementation, verify with packet capture:

1. LabBREW opens TCP control session itself.
2. LabBREW sends ROUTE_REQ and receives status=0 confirmations.
3. If gateway requests auth, LabBREW completes auth exchange.
4. LabBREW emits periodic route/can-info maintenance messages.
5. Agitator actuation remains functional with PCAN Virtual Gateway software fully disconnected.

## Evidence Notes

Decoded evidence came from tshark analyses over the capture file, including:

- TCP stream follows for streams 0..10
- TCP payload packet timeline on port 45321
- UDP endpoint/conversation summaries
- TCP endpoint/conversation summaries
- IO per-second protocol split

If needed, produce a second capture with explicit user markers for phases:

- Phase A: PCAN software disconnected
- Phase B: PCAN software connected
- Phase C: PCAN software disconnected again

Then compare route-state transitions against actuator behavior with exact phase boundaries.

## RX Route Capture Addendum (2026-05-09 11:43)

Additional capture:

- logs/captures/rx_route_auth_capture_20260509_114348.pcapng

### What changed in this capture

The RX route hold flow is gateway-initiated, not host-initiated.

- Initiator for short/long RX sessions: 192.168.5.37 -> 192.168.5.65:45321
- Repeated short streams contain only:
   1. HEJ_REQ
   2. HEJ_CNF
   3. ROUTE_REQ name="rt1" state=0x98000003 port=55001 proto="udp"

One longer RX stream included full auth and keepalive behavior:

1. Gateway sends HEJ_REQ
2. Host replies HEJ_CNF
3. Gateway sends ROUTE_REQ rt1
4. Host replies ROUTE_CNF status=0 state="0x08000002"
5. Gateway sends ROUTE_AUTH_REQ
6. Host replies ROUTE_AUTH_CNF
7. Gateway sends FW_INFO_REQ + DEV_GET_ID_REQ
8. Host replies FW_INFO_CNF + DEV_GET_ID_CNF
9. Gateway repeatedly sends CAN_INFO_REQ
10. Host replies CAN_INFO_CNF each cycle
11. Host sends ROUTE_UPDATE_REQ state="0xc000002"
12. Gateway replies ROUTE_UPDATE_CNF status=0

### Implementation implication

RX parity requires a local TCP listener on control port 45321 that can answer
gateway-initiated HEJ/ROUTE/AUTH/FW/DEV/CAN_INFO messages and periodically send
ROUTE_UPDATE_REQ while the session is open.
