# Individual diagnostic results

Result snapshot events: 1. Devices with snapshots: 1.
These are server-reported results from message type 15. Fresh-run completion and hardware accuracy are not independently established.

| Device | Platform | Reported tests | Pass | Fail | Enabled in matching plan | Missing required |
|---|---|---:|---:|---:|---:|---:|
| device-01 | ios | 44 | 44 | 0 | 46 | 2 |

## Coverage findings

- device-01: all required results accounted for = False.
- No result for Force Touch (iFT-000). Confirm hardware applicability before calling this a failed or omitted test.
- No result for Touch ID (iTI-000). Confirm hardware applicability before calling this a failed or omitted test.

## Individual reported outcomes

| Device | Code | Test | Result |
|---|---|---|---|
| device-01 | iWI-000 | WiFi | Pass |
| device-01 | iGP-000 | GPS | Pass |
| device-01 | iBL-000 | Bluetooth | Pass |
| device-01 | iVI-000 | Vibration | Pass |
| device-01 | iBA-000 | Barometer Sensor | Pass |
| device-01 | iAL-000 | Ambient Light Sensor | Pass |
| device-01 | iGY-000 | Gyro Sensor | Pass |
| device-01 | iLi-000 | LiDAR Sensor | Pass |
| device-01 | iCO-000 | Compass Test | Pass |
| device-01 | iPS-000 | Proximity Sensor | Pass |
| device-01 | iAC-000 | Accelerometer Sensor | Pass |
| device-01 | iNF-000 | NFC Sensor | Pass |
| device-01 | iAM-000 | Auto Mics | Pass |
| device-01 | iAE-000 | Auto Earpiece | Pass |
| device-01 | iAQ-000 | Audio Quality | Pass |
| device-01 | iRP-000 | Record & Play | Pass |
| device-01 | iPR-000 | Play Recorded | Pass |
| device-01 | iHT-000 | Headphones Test | Pass |
| device-01 | iFL-000 | Flashlight | Pass |
| device-01 | iFI-000 | Face ID | Pass |
| device-01 | iFC-000 | Front Camera | Pass |
| device-01 | iRC-000 | Rear Camera | Pass |
| device-01 | iUC-000 | Ultrawide Camera | Pass |
| device-01 | iTC-000 | Telephoto Camera | Pass |
| device-01 | iBS-000 | Barcode Scanner | Pass |
| device-01 | iBRT-000 | Brightness | Pass |
| device-01 | iMT-000 | Multitouch | Pass |
| device-01 | iSR-000 | Screen Rotation | Pass |
| device-01 | iPZ-000 | Pinch Zoom | Pass |
| device-01 | iDGT-000 | Digitizer Test | Pass |
| device-01 | iDGT2-000 | Digitizer Test 2 | Pass |
| device-01 | iLCDC-000 | LCD Check | Pass |
| device-01 | iLCDP-000 | LCD Screen Pixel | Pass |
| device-01 | iNC-000 | Network Connectivity | Pass |
| device-01 | iLC-000 | Live Call | Pass |
| device-01 | iST-000 | SIM Test | Pass |
| device-01 | iWC-000 | Wireless Charging | Pass |
| device-01 | iCP-000 | Charging Port Test | Pass |
| device-01 | iBD-000 | Battery Drain Test | Pass |
| device-01 | iCT-000 | Cosmetics Test | Pass |
| device-01 | iAB-000 | All Buttons | Pass |
| device-01 | iGRD-000 | Grading & Comments | Pass |
| device-01 | iFVC-000 | Front Video Camera | Pass |
| device-01 | iRVC-000 | Rear Video Camera | Pass |

## Completion contract for future load tests

A status=success acknowledgment is insufficient. Observe the correct device's type-15 result snapshot and compare the required test codes with an applicable test plan.
Match the snapshot to the current diagnostic cycle using an authoritative cycle ID or documented fresh-result rule. Type 15 in this capture has no request reference.
A new receive timestamp is not proof the tests ran recently; saved results may be pushed when a device reconnects.
Treat pass/fail as terminal reported outcomes, keep skipped/pending/missing results separate, and require explicit applicability for excluded tests.
Record elapsed time from a verified diagnostic start to its matching final result event; this capture does not establish that start/end pair.
Android requires its own observed result contract and applicable test plan. Do not fabricate passing results or replay this phone's identity.
The current dummy-device runner remains a message-type-1 load test.
