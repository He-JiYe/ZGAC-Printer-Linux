"""One desktop instance per private home; activation carries no credentials."""
import fcntl
import hashlib
import os
import socket
import struct

from zgcaprint.common.errors import PrintError


def address(home):
    digest = hashlib.sha256(os.fsencode(home.resolve())).hexdigest()[:24]
    return '\0zgcaprint-' + str(os.getuid()) + '-' + digest


class Instance:
    def __init__(self, home):
        self.fd = os.open(home/'desktop.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        self.socket = None
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
                sender.settimeout(1)
                try:
                    sender.sendto(b'show', address(home))
                except OSError:
                    raise PrintError('打印驱动正在启动，请稍后重新打开。') from None
            self.primary = False
            return
        self.primary = True
        try:
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            self.socket.bind(address(home))
            self.socket.setblocking(False)
        except Exception:
            self.close()
            raise

    def activated(self):
        if self.socket is None:
            return False
        activated = False
        for _ in range(16):
            try:
                data, ancillary, flags, _ = self.socket.recvmsg(16, socket.CMSG_SPACE(struct.calcsize('3i')))
            except BlockingIOError:
                break
            for level, kind, credentials in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS:
                    _, uid, _ = struct.unpack('3i', credentials)
                    if uid == os.getuid() and not flags & socket.MSG_TRUNC and data == b'show':
                        activated = True
        return activated

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
