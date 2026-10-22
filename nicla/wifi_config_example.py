# Copy this file to wifi_config.py (same folder on the board) and fill it in.
# wifi_config.py is git-ignored so the password never lands on GitHub.

# "sta": join an existing 2.4 GHz network (laptop / phone hotspot recommended;
#        WPA2-Enterprise networks such as campus Wi-Fi do NOT work)
# "ap":  the Nicla creates its own network; connect the laptop to it
WIFI_MODE = "sta"

WIFI_SSID = "my-hotspot"
WIFI_PASS = "password123"

# used only when WIFI_MODE == "ap"
AP_SSID = "nicla-cam"
AP_PASS = "nicla1234"   # >= 8 characters
