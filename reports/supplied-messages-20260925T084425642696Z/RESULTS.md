# Supplied-message replay results

Sent: 11; received: 11 (including unsolicited messages).

One staging account/session, one supplied iOS device, one pass. This is a baseline replay, not a capacity/stress measurement.
The exact supplied requests were used in source order, with fresh correlation references. Recorded command outputs were submitted unchanged; no commands were executed.

| Type | Outcome | Response ms | Details |
|---|---|---:|---|
| 134 | ACK_NO_REFERENCE | 245.9 | Successful reply; source contains no response for this type |
| 119 | ACK_NO_REFERENCE | 247.76 | Successful reply; source contains no response for this type |
| 139 | REFERENCE_DIFFERENCE | 251.76 | reply.device_info.color: value differs; reply.device_info.firmware: value differs; reply.device_info.build_version: value differs; reply.device_info.os_version: value differs; reply.device_info.colors: list differs (expected 3, received 3); reply.validation_info.icloud_status: value differs; reply.validation_info.fmi_status: missing; reply.validation_info.jailbreak_status: missing; reply.validation_info.sim_lock_status: missing; reply.validation_info.esn_status: missing; reply.validation_info.mdm_status: missing; reply.validation_info.manufacturing_date: missing; reply.oem_info.battery: dict -> NoneType; reply.oem_info.screen: dict -> NoneType; reply.oem_info.front_camera: dict -> NoneType; reply.oem_info.back_camera: dict -> NoneType; reply.oem_info.face_id.has_face_id: value differs; reply.oem_info.face_id.distance_sensor: value differs; reply.oem_info.face_id.infrared_camera: value differs; reply.oem_info.face_id.infrared_dot_matrix: value differs; reply.oem_info.face_id.working: value differs; reply.oem_info.touch_id.is_original: bool -> str; reply.oem_info.motherboard: dict -> NoneType; reply.oem_info.bluetooth: dict -> NoneType; reply.oem_info.cellular: dict -> NoneType; reply.oem_info.wifi: dict -> NoneType; reply.oem_info.serial_number: dict -> NoneType; reply.oem_info.total_original_parts: value differs; reply.battery_info.battery_serial: value differs; reply.battery_info.cycle_count: value differs; reply.battery_info.current_capacity: value differs; reply.battery_info.design_capacity: value differs; reply.battery_info.battery_health: value differs; reply.internal_messages: missing |
| 1 | REFERENCE_DIFFERENCE | 304.82 | reply.command.55: additional command; reply.device_info.color: value differs; reply.device_info.colors: list differs (expected 72, received 54) |
| 2 | REFERENCE_DIFFERENCE | 249.65 | reply.colors: list differs (expected 3, received 3) |
| 3 | REFERENCE_DIFFERENCE | 242.72 | reply.command.5: missing |
| 4 | MATCH | 268.41 | Expected reply fields/values match, excluding current_date; extra object fields allowed |
| 5 | REFERENCE_DIFFERENCE | 242.95 | reply.command.38: missing; reply.command.37: missing; reply.command.36: missing; reply.command.43: additional command; reply.command.42: additional command; reply.command.41: additional command |
| 6 | REFERENCE_DIFFERENCE | 270.67 | reply.face_id.distance_sensor: value differs; reply.face_id.infrared_camera: value differs; reply.face_id.infrared_dot_matrix: value differs |
| 7 | MATCH | 244.08 | Expected reply fields/values match, excluding current_date; extra object fields allowed |
| 8 | REFERENCE_DIFFERENCE | 245.91 | reply.sim_lock_status: missing; reply.esn_status: value differs |

Source command outputs contain empty outputs, a go-ios agent warning and a SIM-lock file error. A successful server envelope does not prove those hardware checks succeeded.
REFERENCE_DIFFERENCE reports content/schema drift, not automatically a defect. current_date is excluded from comparison; additional object fields are allowed.
The file does not contain responses for types 134/119; their success envelopes cannot be compared against a source response.
See messages_readable.log for full sent/received JSON, requests.csv for paired data and timings, and recorded_command_outputs.csv for decoded inputs. Authentication fields are redacted.
