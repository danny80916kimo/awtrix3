#!/usr/bin/env python3
"""Lightweight client: sends hook JSON to claudy daemon via Unix socket."""
import socket
import sys

SOCK_PATH = "/tmp/claudy.sock"


def main():
    data = sys.stdin.buffer.read()
    if not data.strip():
        return
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(SOCK_PATH)
        sock.sendall(data)
        sock.shutdown(socket.SHUT_WR)
        sock.close()
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        pass  # Daemon not running; fail silently


if __name__ == "__main__":
    main()
