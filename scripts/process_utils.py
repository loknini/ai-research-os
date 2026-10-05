"""Cross-platform process inspection helpers."""
from __future__ import annotations

import ctypes
import errno
import os


def pid_is_running(pid: int) -> bool:
    """Return whether *pid* identifies a running process without signalling it.

    ``os.kill(pid, 0)`` is the conventional POSIX liveness probe, but it is not
    safe on Windows: signal value ``0`` is also ``CTRL_C_EVENT`` there and can
    interrupt every Python process sharing the target console group.
    """
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True

    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int

        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


__all__ = ["pid_is_running"]
