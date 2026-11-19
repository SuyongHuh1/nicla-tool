# Copy this file to wifi_config.py (same folder on the board) and fill it in.
# wifi_config.py is git-ignored so the password never lands on GitHub.

# "auto": try an existing 2.4 GHz WPA2 network first, then create the Nicla
#         access point if the network is unavailable (recommended on vehicle)
# "sta":  join the existing network only; fail instead of opening an AP
# "ap":   create the Nicla network immediately
WIFI_MODE = "auto"
WIFI_STA_TIMEOUT_MS = 10000

WIFI_SSID = "my-hotspot"
WIFI_PASS = "password123"

# used when WIFI_MODE is "ap", or when "auto" falls back
AP_SSID = "nicla-cam"
AP_PASS = "nicla1234"   # >= 8 characters
