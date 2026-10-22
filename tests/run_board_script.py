"""Run a nicla/*.py board script under CPython with the board shims.
usage: python tests/run_board_script.py nicla/stream_server.py [port]"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "nicla"))
import board_shim  # noqa: E402

board_shim.install()
path = sys.argv[1]
src = open(path, encoding="utf-8").read()
if len(sys.argv) > 2:
    src = src.replace("PORT = 5005", "PORT = %d" % int(sys.argv[2]))
sys.stdout.reconfigure(line_buffering=True)
exec(compile(src, path, "exec"), {"__name__": "__main__"})
