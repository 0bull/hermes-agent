#!/usr/bin/env python3
"""Run the real backend while adapting only its READY announcement to the legacy token."""
from __future__ import annotations

import os
import signal
import subprocess
import sys

python = os.environ["HERMES_DESKTOP_LIFECYCLE_REAL_PYTHON"]
child = subprocess.Popen([python, *sys.argv[1:]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
assert child.stdout is not None


def stop(_signum, _frame):
    child.terminate()


signal.signal(signal.SIGTERM, stop)
try:
    for line in child.stdout:
        sys.stdout.buffer.write(line.replace(b"HERMES_BACKEND_READY", b"HERMES_DASHBOARD_READY"))
        sys.stdout.buffer.flush()
finally:
    if child.poll() is None:
        child.terminate()
    raise SystemExit(child.wait())
