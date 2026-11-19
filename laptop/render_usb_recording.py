"""Render a saved USB session as the same annotated video shown live."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

import viewer


def read_image(path):
    encoded = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(encoded, cv2.IMREAD_COLOR) if len(encoded) else None


def open_writer(path, fps, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if writer.isOpened():
        return writer, path
    writer.release()
    fallback = path.with_suffix(".avi")
    writer = cv2.VideoWriter(
        str(fallback), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    if not writer.isOpened():
        raise RuntimeError("cannot create output video")
    return writer, fallback


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session")
    parser.add_argument("--output")
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--hide-mask", action="store_true")
    args = parser.parse_args(argv)

    session = Path(args.session).resolve()
    rows = [json.loads(line) for line in
            (session / "meta.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if not rows:
        raise RuntimeError("recording metadata is empty")

    output = Path(args.output).resolve() if args.output else session / "screen.mp4"
    writer = None
    written = 0
    try:
        for row in rows:
            frame = read_image(session / "frames" / row["file"])
            if frame is None:
                continue
            header = row.get("hdr", {})
            if args.scale != 1.0:
                frame = cv2.resize(
                    frame, None, fx=args.scale, fy=args.scale,
                    interpolation=cv2.INTER_NEAREST)
            if not args.hide_mask:
                viewer.draw_mask_overlay(frame, header, args.scale)
            viewer.draw_overlay(frame, header, args.scale)
            lines = [
                "USB frame %s | board %.1f fps | q %s" % (
                    header.get("seq", "-"), header.get("fps", 0.0),
                    header.get("q", "-")),
                "det %d | %s | temporal %s" % (
                    len(header.get("det", []) or []),
                    header.get("pipeline", header.get("detector", "?")),
                    "on" if header.get("temporal") else "off"),
                "REC %d" % (written + 1),
            ]
            viewer.draw_hud(frame, lines)
            viewer.draw_controls(frame, True, not args.hide_mask)
            if writer is None:
                writer, output = open_writer(
                    output, max(1.0, args.fps), (frame.shape[1], frame.shape[0]))
            writer.write(frame)
            written += 1
    finally:
        if writer is not None:
            writer.release()
    print(json.dumps({"video": str(output), "frames": written,
                      "fps": args.fps}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
