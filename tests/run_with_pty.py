#!/usr/bin/env python3
"""Run a command in a pseudo-terminal and supply scripted interactive input."""

import errno
import os
import pty
import sys


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("usage: run_with_pty.py INPUT COMMAND [ARG ...]")

    payload = sys.argv[1].encode()
    command = sys.argv[2:]
    pid, master = pty.fork()
    if pid == 0:
        os.execvp(command[0], command)

    os.write(master, payload)
    while True:
        try:
            chunk = os.read(master, 65536)
        except OSError as exc:
            if exc.errno == errno.EIO:
                break
            raise
        if not chunk:
            break
        os.write(sys.stdout.fileno(), chunk)

    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    raise SystemExit(main())
