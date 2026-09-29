"""The real doctor command probe times out and reaps a hung child."""
import os
import sys

from hermes_cli.doctor_tools import _run_ok


def test_doctor_probe_bounds_hung_child(tmp_path):
    pid_file = tmp_path / "child.pid"
    code = ("import os, sys, time; "
            "open(sys.argv[1], 'w', encoding='ascii').write(str(os.getpid())); "
            "time.sleep(30)")
    assert not _run_ok([sys.executable, "-c", code, str(pid_file)], timeout=1)
    assert pid_file.exists(), "the real child did not start"
    pid = int(pid_file.read_text(encoding="ascii"))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("timed-out doctor child was not reaped")
