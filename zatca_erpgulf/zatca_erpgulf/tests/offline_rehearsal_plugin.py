"""Explicit pytest plugin only; never registered in Frappe or production hooks."""

from pathlib import Path

import pytest

from zatca_erpgulf.zatca_erpgulf.tests.rehearsal_guard import OfflineRehearsalGuard
from zatca_erpgulf.zatca_erpgulf.tests.rehearsal_selection import selected_paths


_GUARD = None


def active_guard():
    return _GUARD


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    global _GUARD
    root = Path(__file__).resolve().parents[3]
    allowed = {str((root / name).resolve()) for name in selected_paths(private_sql=True)}
    if (not (root / ".git").is_file() or not config.args
            or any(str(Path(name).resolve()) not in allowed for name in config.args)):
        raise pytest.UsageError("Offline rehearsal requires the isolated worktree and explicit reviewed test files.")
    if _GUARD is not None:
        raise pytest.UsageError("Offline rehearsal is already active.")
    guard = OfflineRehearsalGuard()
    try:
        guard.start()
    except BaseException:
        guard.close()
        raise
    _GUARD = guard


def pytest_terminal_summary(terminalreporter):
    if _GUARD is not None:
        terminalreporter.write_line("Offline guard active: external network/site init denied; fixture-owned Unix SQL only.")


def pytest_unconfigure(config):
    global _GUARD
    guard, _GUARD = _GUARD, None
    if guard is not None:
        guard.close()
