"""
Config defined in a module with postponed evaluation of annotations (PEP 563).
Annotations then reach the metaclass as strings, on every Python version.
Used by `test_valconfig.py::test_future_annotations*`.
"""
from __future__ import annotations

import pathlib
from pathlib import Path
from typing import Optional, Union, Annotated
from pydantic import BaseModel, Field
from valconfig.valconfig import NestedValConfig

class Config(NestedValConfig):
    p: Path = Path("a")
    q: Optional[Path] = None
    s: Path | None = None
    t: Union[Path, None] = None
    u: pathlib.Path = Path("u")
    v: "Optional[Path]" = None           # Quoted twice
    n: Annotated[int, Field(ge=0)] = 0   # Not a Path, but its evaluation must not break anything
    later: Later | None = None   # Forward reference
    class section:
        n: int = 1
        r: Path = Path("b")

class Later(NestedValConfig):
    x: int = 0

Config.model_rebuild()

class TypedNested(NestedValConfig):
    """Nested classes used in annotations must not be converted to sections."""
    class Sub(BaseModel):
        x: int = 0
    class Item(BaseModel):
        x: int = 0
    sub: Sub
    opt: Optional[Sub] = None
    items: list[Item] = []
    class section:
        n: int = 1
