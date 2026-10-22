One shared account; each platform label identifies its assigned simulated device, not separate startup APIs.
Reference startup requests run sequentially once per session. This does not reproduce the desktop's parallel startup timing.
Replies are matched by message type/reference; account and device identity are checked where applicable.
MATCH checks required structure and a stable-value fingerprint; dynamic token/reference/time fields and list ordering are ignored.
VALUE_CHANGED is not automatically an application defect; account configuration may have changed.
No device-specific type-1 reference occurs in the supplied log. Its acknowledgment is explicitly not a full validation.
Android fixtures remain exploratory. No USB actions, returned shell commands, software updates, or full hardware diagnostics are executed.
No verified diagnostic start/final completion contract is available. Missing reference and unexecuted checks never count as MATCH.
