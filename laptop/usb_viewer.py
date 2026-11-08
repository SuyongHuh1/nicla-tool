"""Live Nicla Vision preview over USB, without changing the PC Wi-Fi.

The script interrupts the running board program, starts nicla/usb_preview.py
from the board drive, then displays JPEG frames. Press Q or Escape to quit,
or C to save the current frame in captures/.
"""

import argparse
import os
import struct
import sys
import time

import cv2
import numpy as np
import serial
from serial.tools import list_ports


MAGIC = b"NVJ1"
MAX_JPEG = 2 * 1024 * 1024


def find_nicla_port(requested=None):
    if requested:
        return requested
    ports = list(list_ports.comports())
    arduino = [p.device for p in ports if p.vid == 0x2341]
    if len(arduino) == 1:
        return arduino[0]
    if not arduino:
        raise RuntimeError("Nicla serial port not found; pass --port COMx")
    raise RuntimeError("multiple Arduino ports found: %s; pass --port" % ", ".join(arduino))


def read_exact(port, size):
    data = bytearray()
    while len(data) < size:
        chunk = port.read(size - len(data))
        if not chunk:
            raise TimeoutError("USB frame timed out")
        data.extend(chunk)
    return bytes(data)


def sync_magic(port):
    window = bytearray()
    while True:
        value = port.read(1)
        if not value:
            raise TimeoutError("no USB preview data; is usb_preview.py on the board?")
        window.extend(value)
        if len(window) > len(MAGIC):
            del window[0]
        if bytes(window) == MAGIC:
            return


def start_board_preview(port):
    port.write(b"\x03\x03")
    time.sleep(0.4)
    port.reset_input_buffer()
    port.write(b"exec(open('usb_preview.py').read())\r\n")


def read_frame(port):
    sync_magic(port)
    seq, size = struct.unpack("<II", read_exact(port, 8))
    if size < 32 or size > MAX_JPEG:
        raise RuntimeError("invalid JPEG size %d" % size)
    jpeg = read_exact(port, size)
    image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("invalid JPEG frame %d" % seq)
    return seq, image


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Nicla COM port; auto-detected when omitted")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--frames", type=int, default=0, help="stop after N frames; 0 keeps running")
    parser.add_argument("--out", help="save the last frame to this path")
    args = parser.parse_args(argv)

    port_name = find_nicla_port(args.port)
    ser = serial.Serial(port_name, 115200, timeout=8, write_timeout=3)
    last = None
    count = 0
    try:
        start_board_preview(ser)
        while not args.frames or count < args.frames:
            seq, frame = read_frame(ser)
            last = frame
            count += 1
            if not args.headless:
                shown = frame.copy()
                cv2.putText(shown, "%s frame %d - Q/Esc quit, C capture" % (port_name, seq),
                            (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 0), 1, cv2.LINE_AA)
                cv2.imshow("Nicla Vision USB preview", shown)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("c"):
                    os.makedirs("captures", exist_ok=True)
                    path = os.path.join("captures", time.strftime("usb_%Y%m%d_%H%M%S.jpg"))
                    cv2.imwrite(path, frame)
                    print("saved", path)
        if args.out and last is not None:
            parent = os.path.dirname(os.path.abspath(args.out))
            os.makedirs(parent, exist_ok=True)
            if not cv2.imwrite(args.out, last):
                raise RuntimeError("failed to save %s" % args.out)
        print("received %d frame(s) from %s" % (count, port_name))
        return 0
    finally:
        try:
            ser.write(b"\x03")
        except Exception:
            pass
        ser.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
