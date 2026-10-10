"""Offline-guard/runner negative tests; never exercise a real denied target."""

import pickle
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import frappe
import pytest
import requests

from tools import run_unification_rehearsal as runner
from zatca_erpgulf.zatca_erpgulf.tests import offline_rehearsal_plugin as plugin
from zatca_erpgulf.zatca_erpgulf.tests.rehearsal_guard import (
    OfflineRehearsalGuard, RehearsalBlocked, private_server_commands,
)
from zatca_erpgulf.zatca_erpgulf.tests.rehearsal_selection import selected_paths, LOCAL_SUITES, PRIVATE_SUITES


class SocketStub:
    def __init__(self, family):
        self.family = family


class ChildStub:
    def __init__(self, running=False):
        self.poll = Mock(return_value=None if running else 0)
        self.terminate, self.kill = Mock(), Mock()
        self.wait = Mock(return_value=0)


def registration(guard, monkeypatch):
    # Metadata-only test dependency, no binary is executed by these unit cases.
    monkeypatch.setattr(Path, "is_file", lambda path: True)
    root = guard.new_private_directory()
    return root, guard.register_private_server(root, "/usr/bin/mariadb-install-db", "/usr/sbin/mariadbd")


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6])
@pytest.mark.parametrize("address", [("blocked.invalid", 443), ("127.0.0.1", 3306), ("::1", 443, 0, 0)])
@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_tcp_never_reaches_original_socket_even_for_loopback(family, address, method):
    with OfflineRehearsalGuard() as guard:
        original = guard._connect = guard._connect_ex = Mock()
        with pytest.raises(RehearsalBlocked) as raised:
            getattr(guard, method)(SocketStub(family), address)
        original.assert_not_called()
        assert raised.value.__context__ is None and "blocked.invalid" not in str(raised.value)


@pytest.mark.parametrize("address", ["/run/mysqld/mysqld.sock", "/tmp/not-owned.sock", "relative.sock", b"/tmp/bytes.sock", "\0abstract"])
def test_unknown_unix_sockets_fail_before_original_connection(address):
    with OfflineRehearsalGuard() as guard:
        original = guard._connect = Mock()
        with pytest.raises(RehearsalBlocked):
            guard.connect(SocketStub(socket.AF_UNIX), address)
        original.assert_not_called()


@pytest.mark.parametrize("method,result", [("connect", None), ("connect_ex", 0), ("connect_ex", 111)])
def test_registered_private_peer_only_and_failed_connect_cannot_read(monkeypatch, method, result):
    with OfflineRehearsalGuard() as guard:
        root, _ = registration(guard, monkeypatch)
        original = guard._connect = guard._connect_ex = Mock(return_value=result)
        sock, address = SocketStub(socket.AF_UNIX), str(root / "server.sock")
        assert getattr(guard, method)(sock, address) == result
        original.assert_called_once_with(sock, address)
        read = Mock(return_value=b"synthetic")
        if method == "connect_ex" and result:
            with pytest.raises(RehearsalBlocked):
                guard._io(read)(sock, 10)
            read.assert_not_called()
        else:
            assert guard._io(read)(sock, 10) == b"synthetic"
            read.assert_called_once_with(sock, 10)


def test_registered_socket_symlink_retargeting_is_denied(monkeypatch):
    with OfflineRehearsalGuard() as guard:
        root, _ = registration(guard, monkeypatch)
        (root / "server.sock").symlink_to("/tmp/not-owned.sock")
        original = guard._connect = Mock()
        with pytest.raises(RehearsalBlocked):
            guard.connect(SocketStub(socket.AF_UNIX), str(root / "server.sock"))
        original.assert_not_called()


@pytest.mark.parametrize("name,args", [
    ("create_connection", (("blocked.invalid", 443),)),
    ("getaddrinfo", ("blocked.invalid", 443)),
    ("gethostbyname", ("blocked.invalid",)),
    ("gethostbyname_ex", ("blocked.invalid",)),
    ("gethostbyaddr", ("192.0.2.1",)),
])
def test_socket_dns_entrypoints_are_denied_without_native_calls(monkeypatch, name, args):
    original = Mock()
    monkeypatch.setattr(socket, name, original)
    with OfflineRehearsalGuard():
        with pytest.raises(RehearsalBlocked):
            getattr(socket, name)(*args)
        original.assert_not_called()


@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6, socket.AF_UNIX])
def test_unregistered_or_inherited_peer_cannot_send_or_receive(family):
    with OfflineRehearsalGuard() as guard:
        original = Mock()
        with pytest.raises(RehearsalBlocked):
            guard._io(original)(SocketStub(family), b"PRIVATE-SECRET")
        original.assert_not_called()


@pytest.mark.parametrize("action", ["http", "http_request", "site_init", "site_connect", "udp", "listen", "bind"])
def test_installed_guards_stop_http_site_init_and_server_paths(action):
    with OfflineRehearsalGuard():
        with pytest.raises(RehearsalBlocked) as raised:
            if action == "http":
                requests.Session().send(requests.Request("GET", "https://blocked.invalid").prepare())
            elif action == "http_request":
                requests.Session().get("https://blocked.invalid")
            elif action == "site_init":
                frappe.init(site="PRIVATE-SECRET")
            elif action == "site_connect":
                frappe.connect()
            else:
                # Invoke guarded methods on a stub, never create a real UDP/TCP
                # socket even when the surrounding OS already forbids them.
                sock = SocketStub(socket.AF_INET)
                if action == "udp":
                    socket.socket.sendto(sock, b"PRIVATE-SECRET", ("192.0.2.1", 1234))
                elif action == "bind":
                    socket.socket.bind(sock, ("127.0.0.1", 0))
                else:
                    socket.socket.listen(sock)
        assert "PRIVATE-SECRET" not in str(raised.value)


@pytest.mark.parametrize("change", ["curl", "bench", "shell", "tcp_enabled", "other_socket", "env", "cwd", "executable", "stdin", "string", "tuple_bad_type"])
def test_native_commands_are_exact_allowlist_without_shell_or_ambient_overrides(monkeypatch, change):
    with OfflineRehearsalGuard() as guard:
        root, (_, approved) = registration(guard, monkeypatch)
        guard._popen = Mock()
        command, kwargs = list(approved), dict(stdout=object(), stderr=subprocess.STDOUT)
        if change == "curl":
            command = ["curl", "https://blocked.invalid"]
        elif change == "bench":
            command = ["bench", "restart"]
        elif change == "shell":
            kwargs["shell"] = True
        elif change == "tcp_enabled":
            command.remove("--skip-networking")
        elif change == "other_socket":
            command[3] = "--socket=/run/mysqld/mysqld.sock"
        elif change in ("env", "cwd", "executable", "stdin"):
            kwargs[change] = "PRIVATE-SECRET"
        elif change == "string":
            command = "PRIVATE-SECRET shell command"
        else:
            command = (approved[0], object())
        with pytest.raises(RehearsalBlocked) as raised:
            guard.popen(command, **kwargs)
        guard._popen.assert_not_called()
        assert "PRIVATE-SECRET" not in str(raised.value)


@pytest.mark.parametrize("kind", ["installer", "server"])
def test_only_exact_fixture_command_is_delegated_and_tracked(monkeypatch, kind):
    with OfflineRehearsalGuard() as guard:
        root, commands = registration(guard, monkeypatch)
        assert tuple(commands) == private_server_commands(root, "/usr/bin/mariadb-install-db", "/usr/sbin/mariadbd")
        child, out = ChildStub(), object()
        guard._popen = Mock(return_value=child)
        args = commands[0 if kind == "installer" else 1]
        assert guard.popen(args, stdout=out, stderr=subprocess.STDOUT) is child
        assert guard.native_starts == 1
        guard._popen.assert_called_once_with(args, stdout=out, stderr=subprocess.STDOUT)


def test_owned_child_cleanup_never_uses_process_name_or_service_lookup(monkeypatch):
    guard = OfflineRehearsalGuard()
    with guard:
        _, (_, command) = registration(guard, monkeypatch)
        child = ChildStub(running=True)
        child.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 5), 0]
        guard._popen = Mock(return_value=child)
        guard.popen(command, stdout=object(), stderr=subprocess.STDOUT)
    child.terminate.assert_called_once()
    child.kill.assert_called_once()
    assert child.wait.call_count == 2 and not guard.root.exists()


def test_running_site_context_stops_before_any_registration(monkeypatch):
    monkeypatch.setattr(frappe.local, "site", "PRIVATE-SECRET", raising=False)
    guard = OfflineRehearsalGuard()
    with pytest.raises(RehearsalBlocked):
        guard.start()
    assert not guard.root.exists()


@pytest.mark.parametrize("root", ["/tmp", "/run/mysqld", "/home", "relative"])
def test_nonowned_directory_is_not_a_registration_target(root):
    with OfflineRehearsalGuard() as guard:
        with pytest.raises(RehearsalBlocked):
            guard.register_private_server(root, "/usr/bin/mariadb-install-db", "/usr/sbin/mariadbd")
        assert not guard._commands and not guard._addresses


@pytest.mark.parametrize("installer,server", [("mariadb-install-db", "/usr/sbin/mariadbd"),
    ("/tmp/mariadb-install-db", "/usr/sbin/mariadbd"),
    ("/usr/bin/unknown", "/usr/sbin/mariadbd"),
    ("/usr/bin/mariadb-install-db", "/tmp/mariadbd")])
def test_executable_origin_and_basename_are_checked(monkeypatch, installer, server):
    with OfflineRehearsalGuard() as guard:
        monkeypatch.setattr(Path, "is_file", lambda path: True)
        root = guard.new_private_directory()
        with pytest.raises(RehearsalBlocked):
            guard.register_private_server(root, installer, server)


def test_guard_repr_and_pickle_never_expose_targets():
    with OfflineRehearsalGuard() as guard:
        assert str(guard.root) not in repr(guard)
        with pytest.raises(RehearsalBlocked):
            pickle.dumps(guard)


@pytest.mark.parametrize("private", [False, True])
def test_runner_uses_fixed_manifest_and_clears_inherited_pytest_and_sql_options(monkeypatch, private):
    monkeypatch.setattr(runner.sys, "argv", ["rehearsal"] + (["--private-sql"] if private else []))
    monkeypatch.setenv("PYTEST_ADDOPTS", "PRIVATE-SECRET --site live")
    monkeypatch.setenv("PYTEST_PLUGINS", "unsafe_plugin")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    monkeypatch.setenv("ZATCA_RUN_ISOLATED_MARIADB", "1")
    invoked = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(runner.subprocess, "run", invoked)
    assert runner.main() == 0
    command = invoked.call_args.args[0]
    keywords = invoked.call_args.kwargs
    assert command[:3] == [runner.sys.executable, "-m", "pytest"]
    assert "zatca_erpgulf.zatca_erpgulf.tests.offline_rehearsal_plugin" in command
    assert all(path in command for path in selected_paths(private_sql=private))
    assert keywords["env"]["PYTHONPATH"] == str(keywords["cwd"])
    assert keywords["env"]["PYTEST_ADDOPTS"] == keywords["env"]["PYTEST_PLUGINS"] == ""
    assert keywords["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert ("ZATCA_RUN_ISOLATED_MARIADB" in keywords["env"]) is private
    assert not any("PRIVATE-SECRET" in argument for argument in command)


@pytest.mark.parametrize("option", ["--site", "--url", "--socket", "--otp", "--deploy", "--basetemp"])
def test_runner_rejects_operational_target_options(monkeypatch, option):
    monkeypatch.setattr(runner.sys, "argv", ["rehearsal", option, "PRIVATE-SECRET"])
    invoked = Mock()
    monkeypatch.setattr(runner.subprocess, "run", invoked)
    with pytest.raises(SystemExit) as raised:
        runner.main()
    assert raised.value.code != 0
    invoked.assert_not_called()


@pytest.mark.parametrize("selected", [[], ["."], ["/tmp/unknown.py"], ["zatca_erpgulf/zatca_erpgulf/tests/test_pos_invoice.py"]])
def test_plugin_rejects_broad_or_unreviewed_collection_before_guard(selected, monkeypatch):
    constructed = Mock()
    monkeypatch.setattr(plugin, "OfflineRehearsalGuard", constructed)
    with pytest.raises(pytest.UsageError):
        plugin.pytest_configure(SimpleNamespace(args=selected))
    constructed.assert_not_called()


def test_manifest_is_explicit_unique_and_private_suites_are_opt_in():
    local, all_paths = selected_paths(), selected_paths(private_sql=True)
    assert len(set(local)) == len(LOCAL_SUITES) and len(set(all_paths)) == len(LOCAL_SUITES) + len(PRIVATE_SUITES)
    assert all("mariadb" not in name for name in local)
    assert set(local) < set(all_paths)


@pytest.mark.parametrize("family,fileno", [(socket.AF_INET, None), (socket.AF_INET6, None),
    (socket.AF_INET, 5), (socket.AF_UNIX, 5), (socket.AF_UNIX, 0)])
def test_constructor_denies_non_unix_or_inherited_descriptors_before_native_call(family, fileno):
    with OfflineRehearsalGuard() as guard:
        original = guard._socket_init = Mock()
        with pytest.raises(RehearsalBlocked):
            guard.socket_init(SocketStub(family), family=family, fileno=fileno)
        original.assert_not_called()


def test_private_sql_fixture_without_guard_cannot_discover_binaries_or_start_process(monkeypatch):
    from zatca_erpgulf.zatca_erpgulf.tests import test_journal_repository_mariadb as private

    monkeypatch.setattr(private, "active_guard", lambda: None)
    discovery = Mock()
    monkeypatch.setattr(private.shutil, "which", discovery)
    generator = private.isolated_server.__wrapped__(Mock())
    with pytest.raises(pytest.fail.Exception, match="offline guard"):
        next(generator)
    discovery.assert_not_called()


def test_runner_and_plugin_reject_non_worktree_installation_before_child_or_guard(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda path: False)
    monkeypatch.setattr(runner.sys, "argv", ["rehearsal"])
    child, constructed = Mock(), Mock()
    monkeypatch.setattr(runner.subprocess, "run", child)
    monkeypatch.setattr(plugin, "OfflineRehearsalGuard", constructed)
    with pytest.raises(SystemExit):
        runner.main()
    with pytest.raises(pytest.UsageError):
        plugin.pytest_configure(SimpleNamespace(args=[selected_paths()[0]]))
    child.assert_not_called()
    constructed.assert_not_called()
