"""
Config defined in a module with postponed evaluation of annotations (PEP 563).
Annotations then reach the metaclass as strings, on every Python version.
Used by `test_valconfig.py::test_future_annotations*`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from valconfig.valconfig import NestedValConfig

class Config(NestedValConfig):
    p: Path = Path("a")
    q: Optional[Path] = None
    later: Later | None = None   # Forward reference
    class section:
        n: int = 1
        r: Path = Path("b")

class Later(NestedValConfig):
    x: int = 0

Config.model_rebuild()
