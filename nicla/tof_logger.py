# tof_logger.py - stream VL53L1X distance over USB serial.
#
# Output lines:  T,<board_ms>,<distance_mm or nan>
# Lines starting with '#' are comments (laptop/capture.py ignores them).
#
# Run: save to the board as main.py (OpenMV IDE: Tools > Save open script to
# OpenMV Cam), close OpenMV IDE, press reset, then run laptop/capture.py.
#
# Note: the firmware's built-in vl53l1x driver exposes read() only; ROI and
# timing budget are fixed by the driver. If phase 1 says we need a smaller ROI,
# we switch to the full ST driver (see docs/phase1.md, "ROI").

import time
import camlib

PERIOD_MS = 50   # ~20 Hz

tof = camlib.open_tof()
led = camlib.Led("LED_GREEN")
print("# tof_logger v1 period_ms=%d tof=%s" % (PERIOD_MS, tof is not None))

while True:
    t0 = time.ticks_ms()
    d = camlib.tof_read(tof)
    print("T,%d,%s" % (t0, "nan" if d is None else d))
    led.toggle()
    dt = time.ticks_diff(time.ticks_ms(), t0)
    if dt < PERIOD_MS:
        time.sleep_ms(PERIOD_MS - dt)
