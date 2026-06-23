"""Network helpers for the uFlex Edge Gateway."""
import socket


def get_lan_ipv4() -> str:
    """Best-effort discovery of the edge's LAN-facing IPv4 address.

    Opens a UDP socket "connected" to a public address — no packets are actually sent —
    so the OS picks the local interface that would route outbound traffic, then reads back
    that interface's address. This is the address the patient's phone uses to reach the edge
    on the home LAN. Falls back to loopback if detection fails (e.g. no network).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
