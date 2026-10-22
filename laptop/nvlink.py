"""Laptop side of the Nicla wire protocol (shares nicla/nvproto.py)."""
import json
import os
import socket
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nicla"))
import nvproto  # noqa: E402

MAGIC = nvproto.MAGIC
encode_cmd = nvproto.encode_cmd
pack_prefix = nvproto.pack_prefix
LineReader = nvproto.LineReader

MAX_HEADER = 64 * 1024
MAX_PAYLOAD = 4 * 1024 * 1024


class ProtocolError(Exception):
    pass


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return bytes(buf)


def read_message(sock):
    """Blocking read of one frame message. Returns (header_dict, payload_bytes)."""
    magic = recv_exact(sock, 4)
    if magic != MAGIC:
        raise ProtocolError("bad magic %r" % magic)
    hlen, plen = struct.unpack("<II", recv_exact(sock, 8))
    if hlen > MAX_HEADER or plen > MAX_PAYLOAD:
        raise ProtocolError("message too large (%d, %d)" % (hlen, plen))
    header = json.loads(recv_exact(sock, hlen).decode("utf-8"))
    payload = recv_exact(sock, plen)
    return header, payload


def send_message(sock, header, payload):
    sock.sendall(pack_prefix(header, len(payload)))
    sock.sendall(payload)


def connect(host, port, timeout=5.0):
    s = socket.create_connection((host, port), timeout=timeout)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s
