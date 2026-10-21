from pathlib import Path
import pytest

pytest.importorskip("click")
pytest.importorskip("rich")
from click.testing import CliRunner
from valconfig.cli import cli

@pytest.fixture
def in_tests_dir(monkeypatch):
    monkeypatch.chdir(Path(__file__).parent)
    monkeypatch.setenv("COLUMNS", "200")

def _rows(output):
    """Map option name -> full table row."""
    return {line.split()[0]: line for line in output.splitlines() if line.strip()}

@pytest.mark.parametrize("target", [None, "BigProject.config", "BigProject.config:config", "BigProject.config:Config"])
def test_show(in_tests_dir, target):
    result = CliRunner().invoke(cli, ["show"] + ([target] if target else []))
    assert result.exit_code == 0, result.output
    assert "BigProject.config.Config" in result.output
    rows = _rows(result.output)
    # Values overridden in local.toml
    assert "'Jane'" in rows["log_name"] and "$/local.toml" in rows["log_name"]
    assert "$/local.toml" in rows["use_gpu"]
    # Values from packaged defaults
    assert "3" in rows["n_units"] and "defaults.toml" in rows["n_units"]
    assert "http://example.com" in rows["url"] and "defaults.toml" in rows["url"]

def test_show_no_sources(in_tests_dir):
    result = CliRunner().invoke(cli, ["show", "--no-sources", "--no-types"])
    assert result.exit_code == 0, result.output
    assert "local.toml" not in result.output
    assert "Source" not in result.output

def test_show_bad_target(in_tests_dir):
    result = CliRunner().invoke(cli, ["show", "BigProject.config:nope"])
    assert result.exit_code != 0
    assert "has no attribute 'nope'" in result.output
