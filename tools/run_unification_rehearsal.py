"""Run only reviewed OFFLINE tests from the isolated development worktree.

No site/URL/OTP/CSID/namespace/SQL-host/command override, no Bench operation and
no installation. Private SQL is optional and creates its own TCP-disabled server.
This runner is not an OS sandbox and cannot make a remote acceptance assertion.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Isolated ZATCA development rehearsal; no authority requests or live changes.")
    parser.add_argument("--private-sql", action="store_true", help="Include owned temporary MariaDB fixtures; no tenant connections.")
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not (root / ".git").is_file():
        parser.error("An isolated linked development worktree is required; do not run against the installed application.")
    # The import is intentionally after worktree verification and before pytest;
    # this manifest has no Frappe/application/resource imports or side effects.
    sys.path.insert(0, str(root))
    from zatca_erpgulf.zatca_erpgulf.tests.rehearsal_selection import selected_paths

    environment = dict(os.environ)
    environment.update(PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                       PYTEST_ADDOPTS="", PYTEST_PLUGINS="")
    environment.pop("ZATCA_RUN_ISOLATED_MARIADB", None)
    if options.private_sql:
        environment["ZATCA_RUN_ISOLATED_MARIADB"] = "1"
    command = [sys.executable, "-m", "pytest", "-q", "-c", str(root / "pyproject.toml"),
               "-p", "no:cacheprovider", "-p", "zatca_erpgulf.zatca_erpgulf.tests.offline_rehearsal_plugin",
               *selected_paths(private_sql=options.private_sql), "--tb=short"]
    return subprocess.run(command, cwd=root, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
