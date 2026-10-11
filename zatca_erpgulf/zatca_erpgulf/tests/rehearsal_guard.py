"""Development-only accidental-I/O guard, NOT an OS/security sandbox.

No production registration/import hook. Only fixture-owned Unix SQL sockets and
exact TCP-disabled native MariaDB commands are allowed. Python socket/DNS/HTTP,
site initialization and other subprocess paths fail closed. Reviewed native
programs, monkeypatching, raw syscalls and hostile code are outside this guard.
Never use it as evidence that a real tenant or tax authority accepted anything.
"""

import socket
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from threading import RLock
from unittest.mock import patch
from weakref import WeakSet


SERVER_FLAGS = (
    "--skip-networking", "--skip-log-bin", "--innodb-buffer-pool-size=32M",
    "--innodb-log-file-size=8M", "--innodb-flush-log-at-trx-commit=1",
    "--innodb-use-native-aio=0", "--max-connections=16",
    "--max-allowed-packet=32M", "--performance-schema=OFF",
)


class RehearsalBlocked(RuntimeError):
    """Static code only; never reveal a denied target/command/site/credential."""

    def __init__(self):
        super().__init__("offline_rehearsal_io_blocked")


def private_server_commands(root, installer, server):
    """Construct the one reviewed native fixture shape, never arbitrary options."""
    root = Path(root)
    install = [installer, "--no-defaults", f"--datadir={root / 'data'}",
               "--auth-root-authentication-method=normal", "--skip-test-db"]
    start = [server, "--no-defaults", f"--datadir={root / 'data'}",
             f"--socket={root / 'server.sock'}", f"--pid-file={root / 'server.pid'}", *SERVER_FLAGS]
    return install, start


class OfflineRehearsalGuard:
    """Process-local test guard; registries cannot be configured from env/site.

    Owned scratch directories are created below /tmp and removed after owned
    subprocess cleanup. No socket/host/datadir/command override is accepted.
    Registrations are trusted fixture actions, not proof against hostile code.
    """

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="zatca-offline-", dir="/tmp")
        self.root = Path(self._temporary.name)
        self.root.chmod(0o700)
        self._directories, self._addresses, self._commands = set(), set(), set()
        self._connected, self._children = WeakSet(), []
        self._lock, self._stack = RLock(), None
        self.denied, self.native_starts = 0, 0
        self._connect, self._connect_ex, self._popen = socket.socket.connect, socket.socket.connect_ex, subprocess.Popen
        self._socket_init = socket.socket.__init__

    def __repr__(self):
        return "OfflineRehearsalGuard(<owned synthetic rehearsal only>)"

    def __reduce_ex__(self, protocol):
        raise RehearsalBlocked()

    def block(self, *args, **kwargs):
        with self._lock:
            self.denied += 1
        raise RehearsalBlocked()

    def new_private_directory(self):
        if self._stack is None:
            self.block()
        directory = Path(tempfile.mkdtemp(prefix="db-", dir=self.root))
        directory.chmod(0o700)
        with self._lock:
            self._directories.add(directory)
        return directory

    def register_private_server(self, root, installer, server):
        root = Path(root)
        if root not in self._directories or root.resolve() != root or root.parent != self.root:
            self.block()
        paths = [Path(value) for value in (installer, server)]
        for path, name in zip(paths, ("mariadb-install-db", "mariadbd")):
            if (not path.is_absolute() or path.name != name or path.resolve().parent not in (Path("/usr/bin"), Path("/usr/sbin"))
                    or not path.is_file()):
                self.block()
        install, start = private_server_commands(root, installer, server)
        with self._lock:
            self._addresses.add(str(root / "server.sock"))
            self._commands.update((tuple(install), tuple(start)))
        return install, start

    def _check_address(self, sock, address):
        if sock.family != socket.AF_UNIX or type(address) is not str or not address.startswith("/"):
            self.block()
        # Resolve each time: a symlink to a running/foreign SQL socket is denied.
        if str(Path(address).resolve()) != address or address not in self._addresses:
            self.block()

    def socket_init(self, sock, family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0, fileno=None):
        # Reject even loopback TCP creation and inherited descriptor adoption.
        # Registered Unix peers are checked again at connect and every read/write.
        if family != socket.AF_UNIX or fileno is not None:
            self.block()
        return self._socket_init(sock, family, type, proto, fileno)

    def connect(self, sock, address):
        self._check_address(sock, address)
        result = self._connect(sock, address)
        with self._lock:
            self._connected.add(sock)
        return result

    def connect_ex(self, sock, address):
        self._check_address(sock, address)
        result = self._connect_ex(sock, address)
        if result == 0:
            with self._lock:
                self._connected.add(sock)
        return result

    def _io(self, original):
        def checked(sock, *args, **kwargs):
            with self._lock:
                allowed = sock.family == socket.AF_UNIX and sock in self._connected
            if not allowed:
                self.block()
            return original(sock, *args, **kwargs)
        return checked

    def popen(self, args, *positional, **kwargs):
        if (type(args) not in (list, tuple) or any(type(value) is not str for value in args)
                or tuple(args) not in self._commands or positional or set(kwargs) != {"stdout", "stderr"}
                or kwargs["stderr"] != subprocess.STDOUT):
            self.block()
        child = self._popen(args, **kwargs)
        with self._lock:
            self._children.append(child)
            self.native_starts += 1
        return child

    def start(self):
        if self._stack is not None:
            self.block()
        stack = self._stack = ExitStack()
        try:
            for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
                stack.enter_context(patch.object(socket, name, self.block))
            # Keep socket as a class: SSL imports/subclasses must remain valid.
            stack.enter_context(patch.object(socket.socket, "__init__", lambda sock, family=socket.AF_INET,
                type=socket.SOCK_STREAM, proto=0, fileno=None: self.socket_init(sock, family, type, proto, fileno)))
            stack.enter_context(patch.object(socket.socket, "connect", lambda sock, address: self.connect(sock, address)))
            stack.enter_context(patch.object(socket.socket, "connect_ex", lambda sock, address: self.connect_ex(sock, address)))
            for name in ("send", "sendall", "recv", "recv_into", "recvfrom", "recvfrom_into", "sendfile"):
                stack.enter_context(patch.object(socket.socket, name, self._io(getattr(socket.socket, name))))
            for name in ("sendto", "sendmsg", "recvmsg", "recvmsg_into", "bind", "listen", "accept"):
                if hasattr(socket.socket, name):
                    stack.enter_context(patch.object(socket.socket, name, self.block))
            stack.enter_context(patch.object(subprocess, "Popen", self.popen))
            import requests
            import frappe

            if getattr(frappe.local, "site", None) is not None:
                self.block()
            # Stop normal requests BEFORE Session preparation can discover
            # ambient authentication/proxy settings; raw adapter fakes remain.
            stack.enter_context(patch.object(requests.Session, "request", self.block))
            stack.enter_context(patch.object(requests.Session, "send", self.block))
            stack.enter_context(patch.object(frappe, "init", self.block))
            stack.enter_context(patch.object(frappe, "connect", self.block))
            # An unmocked translation/error path can discover a bench log file
            # without initializing a site. Refuse that before file discovery.
            stack.enter_context(patch.object(frappe, "logger", self.block))
        except BaseException:
            self.close()
            raise
        return self

    def close(self):
        # Only exact Popen objects created by approved fixture commands, never
        # process-name lookup, service/Bench commands or an unrelated process.
        for child in self._children:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        if self._stack is not None:
            self._stack.close()
            self._stack = None
        self._temporary.cleanup()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()
