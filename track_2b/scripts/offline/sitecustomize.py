"""Egress guard for the offline proof (scripts/offline_job.sh): imported by every Python process started with this
folder on PYTHONPATH (vLLM and the auditor). Any connection to an address outside this machine is refused and
logged; loopback and the machine's own addresses stay allowed (vLLM talks to itself over them).

Python sockets only: native code that opens its own sockets is not covered, which is why the job also reads the
kernel's byte counters per interface.
"""

import contextlib
import ipaddress
import os
import socket
import sys

_LOG = os.environ.get("EGRESS_LOG", "/tmp/offline/egress_blocked.log")
_connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex


def _own_addresses() -> set[str]:
    own = {"127.0.0.1", "::1"}
    with contextlib.suppress(OSError):  # resolved from /etc/hosts, no network
        own.update(a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None))
    return own


_OWN = _own_addresses()


def _local(address: object) -> bool:
    if not isinstance(address, tuple):  # AF_UNIX paths
        return True
    host = str(address[0])
    try:
        return ipaddress.ip_address(host).is_loopback or host in _OWN
    except ValueError:
        return host in ("localhost", socket.gethostname())


def _refuse(sock: socket.socket, address: object) -> None:
    line = f"BLOCKED pid={os.getpid()} {sys.argv[0].rsplit('/', 1)[-1]} -> {address}\n"
    with contextlib.suppress(OSError), open(_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    raise ConnectionRefusedError(f"offline mode: outbound connection to {address} refused")


def connect(self: socket.socket, address: object) -> None:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(address):
        _refuse(self, address)
    return _connect(self, address)


def connect_ex(self: socket.socket, address: object) -> int:
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(address):
        _refuse(self, address)
    return _connect_ex(self, address)


socket.socket.connect = connect  # type: ignore[method-assign]
socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
