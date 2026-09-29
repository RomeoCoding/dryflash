"""Process and port helpers shared by sessions."""

from __future__ import annotations

import ctypes
import signal
import socket
import sys
import threading

_PR_SET_PDEATHSIG = 1


def die_with_parent() -> None:
    """preexec_fn: have the kernel SIGKILL the child if the server dies without cleaning up."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)


class PortAllocator:
    """Hands out free localhost TCP ports and never reuses one that a live session still holds.

    Asking the kernel for port 0 alone is not enough: two sessions started back to back could be
    given the same port between our close() and QEMU's bind().
    """

    def __init__(self):
        self._held: set[int] = set()
        self._lock = threading.Lock()

    def allocate(self) -> int:
        with self._lock:
            for _ in range(100):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(("127.0.0.1", 0))
                    port = s.getsockname()[1]
                if port not in self._held:
                    self._held.add(port)
                    return port
        raise RuntimeError("could not find a free TCP port")

    def release(self, port: int) -> None:
        with self._lock:
            self._held.discard(port)
