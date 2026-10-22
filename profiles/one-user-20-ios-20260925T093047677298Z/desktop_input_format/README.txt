Each device folder contains input.txt in exactly the Desktop battery JSON structure and its verified encoder output.txt.
all_20_battery_inputs.json groups the 20 battery objects by device name.
device_mapping.json maps each battery serial to its simulated device UDID and device serial. UDID is not a field in the supplied battery JSON schema.
Battery values are preserved as requested, including current_capacity greater than design_capacity. No staging run performed. Original Desktop files unchanged.
