from pathlib import Path
import pytest

@pytest.fixture(autouse=True)
def in_tests_dir(monkeypatch):
    # Local config files are searched for starting from the current directory
    monkeypatch.chdir(Path(__file__).parent)
