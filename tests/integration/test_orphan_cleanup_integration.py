"""
Integration test: the retriever subprocess must exit when its parent dies without calling stop().
"""

import os
import signal
import subprocess
import sys
import time

PARENT_SCRIPT = """
import sys, threading, time
from ax_devil_rtsp.rtsp_data_retrievers import RtspVideoDataRetriever

got_frame = threading.Event()
retriever = RtspVideoDataRetriever(sys.argv[1], on_video_data=lambda _: got_frame.set(), connection_timeout=10)
retriever.start()
if not got_frame.wait(60):
    sys.exit(2)
print(retriever._proc.pid, flush=True)
time.sleep(600)
"""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_child_exits_when_parent_is_killed(rtsp_url):
    parent = subprocess.Popen([sys.executable, "-c", PARENT_SCRIPT, rtsp_url], stdout=subprocess.PIPE, text=True)
    try:
        line = parent.stdout.readline()
        assert line, f"Parent produced no child PID (exit code {parent.poll()})"
        child_pid = int(line)
        assert _pid_alive(child_pid)

        parent.send_signal(signal.SIGKILL)
        parent.wait()

        deadline = time.monotonic() + 10
        while _pid_alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        alive = _pid_alive(child_pid)
        if alive:
            os.kill(child_pid, signal.SIGKILL)
        assert not alive, "Retriever subprocess outlived its killed parent"
    finally:
        if parent.poll() is None:
            parent.kill()
