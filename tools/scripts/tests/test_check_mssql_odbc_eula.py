"""Tests for the Microsoft ODBC Driver license acceptance gate."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "check-mssql-odbc-eula"


def run_check(acceptance_file):
    return subprocess.run(
        [str(SCRIPT)],
        env={"MSSQL_ODBC_EULA_FILE": str(acceptance_file), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )


def test_missing_marker_fails_with_instructions(tmp_path):
    result = run_check(tmp_path / "absent")
    assert result.returncode == 1
    assert "license acceptance is required" in result.stderr
    assert "MICROSOFT_ODBC_DRIVER_FOR_SQL_SERVER_LICENSE.txt" in result.stderr
    assert ".accept-mssql-odbc-eula" in result.stderr


def test_present_marker_passes(tmp_path):
    marker = tmp_path / "marker"
    marker.write_text("")
    result = run_check(marker)
    assert result.returncode == 0
    assert result.stderr == ""
