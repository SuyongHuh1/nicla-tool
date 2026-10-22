# nvproto.py - Nicla <-> laptop wire protocol (MicroPython + CPython compatible)
#
# Board -> laptop (one message per camera frame):
#   b"NV01" | uint32 LE header_len | uint32 LE payload_len | header JSON (utf-8) | payload (JPEG)
#
# Laptop -> board (commands):
#   one JSON object per line, terminated by b"\n"
#
# Keep this file free of board-only imports so the laptop tests can import it.

import struct

try:
    import ujson as json
except ImportError:
    import json

MAGIC = b"NV01"
PROTO_VERSION = 1


def pack_prefix(header, payload_len):
    """Return MAGIC + lengths + header bytes. Send the payload separately
    (avoids copying the JPEG into a second buffer on the board)."""
    h = json.dumps(header)
    if not isinstance(h, bytes):
        h = h.encode()
    return MAGIC + struct.pack("<II", len(h), payload_len) + h


def encode_cmd(cmd):
    s = json.dumps(cmd)
    if not isinstance(s, bytes):
        s = s.encode()
    return s + b"\n"


class LineReader:
    """Accumulates bytes and yields complete JSON command objects."""

    def __init__(self, maxlen=2048):
        self.buf = b""
        self.maxlen = maxlen

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            i = self.buf.find(b"\n")
            if i < 0:
                break
            line = self.buf[:i].strip()
            self.buf = self.buf[i + 1:]
            if not line:
                continue
            try:
                obj = json.loads(line.decode())
            except (ValueError, UnicodeError):
                obj = None
            if isinstance(obj, dict):
                out.append(obj)
            else:
                out.append({"t": "_bad"})
        if len(self.buf) > self.maxlen:  # garbage without newline
            self.buf = b""
        return out
