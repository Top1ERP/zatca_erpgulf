"""Private database bootstrap diagnostics; no native binary or process needed."""

import subprocess

import pytest

from zatca_erpgulf.zatca_erpgulf.tests.offline_rehearsal_plugin import active_guard
from zatca_erpgulf.zatca_erpgulf.tests import test_journal_repository_mariadb as harness


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_private_installer_failure_keeps_only_a_bounded_log_tail(monkeypatch, failure):
    guard = active_guard()
    starts = guard.native_starts
    calls = []
    # Local diagnostics do not require native binaries and register NO allowed
    # command. If the failure path accidentally starts a server, the real guard
    # still rejects it. Only the installer result below is simulated.
    monkeypatch.setattr(harness.shutil, "which", lambda name: "/never-start/" + name)
    def commands(root, installer, server):
        assert root.parent == guard.root
        return [installer, "--no-defaults", "--skip-test-db"], [server, "--no-defaults", "--skip-networking"]
    monkeypatch.setattr(guard, "register_private_server", commands)
    def failed_install(command, *, check, stdout, stderr, timeout):
        calls.append(tuple(command))
        assert command[0].endswith("/mariadb-install-db")
        assert "--no-defaults" in command and "--skip-test-db" in command
        assert check is True and stderr is subprocess.STDOUT and timeout == 30
        stdout.write(b"EARLY-DISCARDED\n" + b"x" * 8192 + b"\nSYNTHETIC-INSTALL-FAILURE\xff")
        stdout.flush()
        if failure == "exit": raise subprocess.CalledProcessError(1, command)
        raise subprocess.TimeoutExpired(command, timeout)
    monkeypatch.setattr(subprocess, "run", failed_install)
    generator = harness.isolated_server.__wrapped__(None)
    with pytest.raises(pytest.fail.Exception) as caught:
        next(generator)
    message = str(caught.value)
    assert message.startswith("Private MariaDB installation failed.")
    assert "SYNTHETIC-INSTALL-FAILURE" in message and "EARLY-DISCARDED" not in message
    assert len(message) < 4200
    assert len(calls) == 1 and guard.native_starts == starts
