# camlib.py - hardware helpers for Arduino Nicla Vision (OpenMV firmware)
#
# Works with both the new `csi` camera API (OpenMV >= 4.7) and the legacy
# `sensor` module, so it does not matter which firmware is on the board.

import time

try:
    import csi
    _NEW_API = True
except ImportError:
    import sensor
    _NEW_API = False


class Camera:
    def __init__(self, framesize="QVGA", pixformat="RGB565", warmup_ms=2000):
        if _NEW_API:
            self.c = csi.CSI()
            self.c.reset()
            self.c.pixformat(getattr(csi, pixformat))
            self.c.framesize(getattr(csi, framesize))
            self.c.snapshot(time=warmup_ms)  # let auto exposure settle
        else:
            sensor.reset()
            sensor.set_pixformat(getattr(sensor, pixformat))
            sensor.set_framesize(getattr(sensor, framesize))
            sensor.skip_frames(time=warmup_ms)
        self.locked = False

    def snapshot(self):
        return self.c.snapshot() if _NEW_API else sensor.snapshot()

    def state(self):
        """Current exposure (us), gain (dB), white-balance gains (dB). None if unsupported."""
        exp = gain = wb = None
        try:
            exp = self.c.exposure_us() if _NEW_API else sensor.get_exposure_us()
        except Exception:
            pass
        try:
            gain = self.c.gain_db() if _NEW_API else sensor.get_gain_db()
        except Exception:
            pass
        try:
            wb = self.c.rgb_gain_db() if _NEW_API else sensor.get_rgb_gain_db()
        except Exception:
            pass
        return exp, gain, wb

    def lock(self, exposure_us=None, gain_db=None, rgb_gain_db=None):
        """Freeze auto gain / white balance / exposure.
        Values left as None are taken from what auto mode converged to."""
        exp0, gain0, wb0 = self.state()
        exposure_us = exposure_us if exposure_us is not None else exp0
        gain_db = gain_db if gain_db is not None else gain0
        rgb_gain_db = rgb_gain_db if rgb_gain_db is not None else wb0
        errors = []
        for name, fn in (("gain", self._lock_gain), ("whitebal", self._lock_wb),
                         ("exposure", self._lock_exp)):
            try:
                fn(exposure_us, gain_db, rgb_gain_db)
            except Exception as e:
                errors.append("%s:%s" % (name, e))
        self.locked = True
        return errors

    def _lock_gain(self, e, g, wb):
        if _NEW_API:
            self.c.auto_gain(False, gain_db=g) if g is not None else self.c.auto_gain(False)
        else:
            sensor.set_auto_gain(False, gain_db=g) if g is not None else sensor.set_auto_gain(False)

    def _lock_wb(self, e, g, wb):
        if _NEW_API:
            self.c.auto_whitebal(False, rgb_gain_db=wb) if wb is not None else self.c.auto_whitebal(False)
        else:
            sensor.set_auto_whitebal(False, rgb_gain_db=wb) if wb is not None else sensor.set_auto_whitebal(False)

    def _lock_exp(self, e, g, wb):
        if _NEW_API:
            self.c.auto_exposure(False, exposure_us=int(e)) if e is not None else self.c.auto_exposure(False)
        else:
            sensor.set_auto_exposure(False, exposure_us=int(e)) if e is not None else sensor.set_auto_exposure(False)


def jpeg_bytes(img, quality=50):
    """Compress a COPY of img (img itself stays usable) and return bytes-like."""
    try:
        j = img.to_jpeg(quality=quality, copy=True)
    except (AttributeError, TypeError):
        j = img.compressed(quality=quality)
    return j.bytearray()


def open_tof():
    """VL53L1X on the internal I2C bus 2. Returns None if not available."""
    try:
        from machine import I2C
        import vl53l1x
        return vl53l1x.VL53L1X(I2C(2))
    except Exception as e:
        print("# tof unavailable:", e)
        return None


def tof_read(tof):
    if tof is None:
        return None
    try:
        return tof.read()
    except Exception:
        return None


class Led:
    """Status LED that works on new (machine.LED) and old (pyb.LED) firmware."""

    def __init__(self, color="LED_BLUE"):
        self.led = None
        try:
            from machine import LED
            self.led = LED(color)
        except Exception:
            try:
                import pyb
                self.led = pyb.LED({"LED_RED": 1, "LED_GREEN": 2, "LED_BLUE": 3}[color])
            except Exception:
                pass
        self.state = False

    def set(self, on):
        if self.led is None:
            return
        self.state = on
        self.led.on() if on else self.led.off()

    def toggle(self):
        self.set(not self.state)


class Illuminator:
    """External illumination LED switched through a logic-level MOSFET on a
    header pin (default D0). The Nicla pins supply only a few mA behind level
    shifters - never drive the LED directly from the pin."""

    def __init__(self, pin_name="D0", active_high=True):
        self.pin = None
        self.active_high = active_high
        self.on = False
        if pin_name:
            try:
                from machine import Pin
                self.pin = Pin(pin_name, Pin.OUT)
            except Exception as e:
                print("# illum unavailable:", e)
        self.set(False)

    def available(self):
        return self.pin is not None

    def set(self, on):
        self.on = bool(on)
        if self.pin is not None:
            self.pin.value(1 if self.on == self.active_high else 0)


def flicker_safe_us(exposure_us, mains_hz=60):
    """Round an exposure to a whole number of mains flicker periods
    (lights flicker at 2x mains: 8333 us in Korea). Integrating whole periods
    makes every frame collect the same ambient light, which keeps LED on/off
    difference images clean."""
    period = 1000000.0 / (2 * mains_hz)
    n = max(1, int(exposure_us / period + 0.5))
    return int(n * period)


def ticks():
    return time.ticks_ms()
