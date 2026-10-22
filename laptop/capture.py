"""Log measurement lines from the Nicla's USB serial port into a CSV.

Examples (Windows):
  py laptop\\capture.py --list
  py laptop\\capture.py --kind tof --label h05_b30 --n 100
  py laptop\\capture.py --kind exposure --label lock_led_on --seconds 600

The board must be running nicla/tof_logger.py or nicla/exposure_test.py as
main.py, and OpenMV IDE must be closed (it holds the serial port).
"""
import argparse
import csv
import os
import re
import sys
import time

KINDS = {
    "tof": ("T", ["board_ms", "distance_mm"]),
    "exposure": ("E", ["board_ms", "l_mean", "l_stdev", "exposure_us", "gain_db"]),
}
KNOWN_VIDS = {0x2341: "Arduino", 0x37C5: "OpenMV", 0x1209: "OpenMV(old)"}
LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def list_ports():
    from serial.tools import list_ports as lp
    return list(lp.comports())


def pick_port():
    ports = list_ports()
    cands = [p for p in ports if p.vid in KNOWN_VIDS]
    if len(cands) == 1:
        return cands[0].device
    print("Could not pick a port automatically. Available ports:")
    for p in ports:
        print("  %-8s vid=%s %s" % (p.device, hex(p.vid) if p.vid else "-", p.description))
    sys.exit("Use --port COMx")


def parse_line(line, prefix, ncols):
    """'T,123,456' -> ['123', '456'] (None if not a data line of this kind)."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split(",")
    if parts[0] != prefix or len(parts) != ncols + 1:
        return None
    return parts[1:]


def run(lines, writer, prefix, ncols, n=None, seconds=None, skip=0, echo=True):
    """Consume an iterator of text lines. Returns number of rows written."""
    rows = 0
    skipped = 0
    t0 = time.monotonic()
    for line in lines:
        if line.startswith("#") and echo:
            print(line.strip())
        vals = parse_line(line, prefix, ncols)
        if vals is not None:
            if skipped < skip:
                skipped += 1
            else:
                writer.writerow(vals)
                rows += 1
                if echo and rows % 20 == 0:
                    print("  %d rows  last=%s" % (rows, ",".join(vals)))
        if n is not None and rows >= n:
            break
        if seconds is not None and time.monotonic() - t0 >= seconds:
            break
    return rows


def serial_lines(port, baud=115200, timeout=1.0):
    import serial
    with serial.Serial(port, baud, timeout=timeout) as ser:
        ser.reset_input_buffer()
        idle = 0
        while True:
            raw = ser.readline()
            if not raw:
                idle += 1
                if idle == 5:
                    print("! no data for 5 s - is the script saved as main.py and OpenMV IDE closed?")
                continue
            idle = 0
            yield raw.decode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    ap.add_argument("--port", help="COM port (auto-detected if only one Arduino/OpenMV device)")
    ap.add_argument("--kind", choices=KINDS, default="tof")
    ap.add_argument("--label", help="condition label, e.g. h05_b30 or h05_b30_t45 (see docs/phase1.md)")
    ap.add_argument("--n", type=int, help="rows to record (default 100 for tof)")
    ap.add_argument("--seconds", type=float, help="record for this long instead of --n")
    ap.add_argument("--skip", type=int, default=10, help="discard the first N rows (settling)")
    ap.add_argument("--out", default="results")
    ap.add_argument("--force", action="store_true", help="overwrite an existing file")
    a = ap.parse_args(argv)

    if a.list:
        for p in list_ports():
            print("%-8s vid=%s %s" % (p.device, hex(p.vid) if p.vid else "-", p.description))
        return 0
    if not a.label or not LABEL_RE.match(a.label):
        ap.error("--label is required (letters, digits, _ . - only)")
    if a.n is None and a.seconds is None:
        a.n = 100
    prefix, cols = KINDS[a.kind]
    outdir = os.path.join(a.out, a.kind)
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, a.label + ".csv")
    if os.path.exists(path) and not a.force:
        sys.exit("%s exists (use --force to overwrite)" % path)
    port = a.port or pick_port()
    print("recording %s -> %s from %s" % (a.kind, path, port))
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        rows = run(serial_lines(port), w, prefix, len(cols), n=a.n, seconds=a.seconds, skip=a.skip)
    print("done: %d rows -> %s" % (rows, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
