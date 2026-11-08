"""Stream camera JPEG frames over the Nicla USB virtual serial port.

Run this from the OpenMV REPL or let laptop/usb_viewer.py start it. Ctrl-C
stops the stream and returns to the REPL.
"""

import struct
import time
import pyb

import camlib


MAGIC = b"NVJ1"
JPEG_QUALITY = 45


def write_all(usb, data):
    view = memoryview(data)
    while len(view):
        count = usb.write(view)
        if not count:
            time.sleep_ms(5)
            continue
        view = view[count:]


def main():
    usb = pyb.USB_VCP()
    cam = camlib.Camera(framesize="QVGA", pixformat="RGB565", warmup_ms=1500)
    seq = 0
    while True:
        if not usb.isconnected():
            time.sleep_ms(50)
            continue
        jpeg = camlib.jpeg_bytes(cam.snapshot(), JPEG_QUALITY)
        write_all(usb, MAGIC)
        write_all(usb, struct.pack("<II", seq, len(jpeg)))
        write_all(usb, jpeg)
        seq = (seq + 1) & 0xFFFFFFFF


main()
