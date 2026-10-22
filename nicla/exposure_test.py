# exposure_test.py - check whether image brightness stays stable with the
# camera settings locked (or not, for comparison).
#
# Output lines:  E,<board_ms>,<l_mean>,<l_stdev>,<exposure_us>,<gain_db>
# l_mean / l_stdev = LAB lightness statistics of the centre 50% of the frame.
#
# Run as main.py (like tof_logger.py) and log with:
#   py laptop\capture.py --kind exposure --label lock_led_on --seconds 600

import time
import camlib

LOCK = True          # False = leave auto exposure/gain/white balance on (baseline)
PERIOD_MS = 500

cam = camlib.Camera("QVGA")
errs = cam.lock() if LOCK else []
exp, gain, wb = cam.state()
print("# exposure_test v1 lock=%s exp_us=%s gain_db=%s wb=%s errors=%s" % (LOCK, exp, gain, wb, errs))

led = camlib.Led("LED_GREEN")
roi = None
while True:
    t0 = time.ticks_ms()
    img = cam.snapshot()
    if roi is None:
        w, h = img.width(), img.height()
        roi = (w // 4, h // 4, w // 2, h // 2)
    st = img.get_statistics(roi=roi)
    exp, gain, _ = cam.state()
    print("E,%d,%d,%d,%s,%s" % (t0, st.l_mean(), st.l_stdev(),
                                "nan" if exp is None else exp,
                                "nan" if gain is None else ("%.2f" % gain)))
    led.toggle()
    dt = time.ticks_diff(time.ticks_ms(), t0)
    if dt < PERIOD_MS:
        time.sleep_ms(PERIOD_MS - dt)
