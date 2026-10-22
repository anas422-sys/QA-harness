One user, 15 simulated iOS profiles. No staging calls or hardware commands executed.
Battery files were encoded with the supplied Desktop encoder.exe and all 15 outputs decoded back to the exact input bytes.
Original Desktop input.txt and output.txt are unchanged (SHA256 verified).
devices.csv lists identities and battery values; each device folder has battery_input.json, battery_encoded.txt, device_info_decoded.plist and profile.json.
profiles.json includes session request templates (134,119) and nine device requests (139,1,2,3,4,5,6,7,8) per profile. Refs must be refreshed on reuse.
Device UDID, device serial and battery serial are synthetic and consistently replaced in requests, command arguments and decoded outputs.
The user-provided battery values are intentionally preserved: design 2030, current 3720, health 80, cycles 260, analytics true. Current capacity exceeds design capacity. These are unusual-data fixtures, not physically consistent measurements.
Other historic measurements, part records, warnings and command errors remain from the source. Empty OEM outputs and SIM-lock file errors are not repaired by encoding.
Encoding success does not guarantee backend acceptance or real hardware results. These templates replay recorded outputs; returned command lists may change.
