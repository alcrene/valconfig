"""
Backport of the pathlib subclassing API introduced in Python 3.12.

Starting with Python 3.12, `Path` can be subclassed directly: construction calls
`__init__(*pathsegments)`, and every derived path (`p / "a"`, `p.parent`, ...)
is created with `p.with_segments(...)`, which allows subclasses to pass along
additional attributes. `ConfigPath` relies on both.

On Python ≥ 3.12, `PathBase` is simply `Path`. On earlier versions, it is a
subclass of the concrete path class (`PosixPath` or `WindowsPath`) which
reproduces this API by hooking into the private construction methods of
pathlib. This is safe because the pathlib of these older versions is frozen,
receiving only security fixes.

Differences with Python 3.12 on older versions:
- `parents` returns a tuple instead of a sequence object.
"""

import sys
from functools import partial
from pathlib import Path

__all__ = ["PathBase"]

if sys.version_info >= (3, 12):
    PathBase = Path

else:
    class _hybridmethod:
        """
        Like `classmethod`, except that when accessed through an instance,
        the instance rather than the class is passed as first argument.
        """
        def __init__(self, func):
            self.func = func
        def __get__(self, obj, objtype=None):
            return partial(self.func, objtype if obj is None else obj)

    class PathBase(type(Path())):  # `PosixPath` or `WindowsPath`
        __slots__ = ()

        def __new__(cls, *args, **kwargs):
            # Construction is done in `__init__`, as on Python ≥ 3.12
            return object.__new__(cls)

        def __init__(self, *pathsegments):
            self._drv, self._root, self._parts = self._parse_args(pathsegments)

        def with_segments(self, *pathsegments):
            return type(self)(*pathsegments)

        # pathlib calls these two classmethods to create every derived path,
        # through the instance (`self._from_parts(...)`) except for `parents`.
        # Through an instance, we redirect them to `with_segments`.

        @_hybridmethod
        def _from_parts(owner, args):
            if isinstance(owner, type):
                return owner(*args)
            return owner.with_segments(*args)

        @_hybridmethod
        def _from_parsed_parts(owner, drv, root, parts):
            path_str = owner._format_parsed_parts(drv, root, parts)
            if isinstance(owner, type):
                return owner(path_str)
            return owner.with_segments(path_str)

        @property
        def parents(self):
            # pathlib’s `_PathParents` creates paths through the class, bypassing `with_segments`
            parents = []
            path = self
            while (parent := path.parent) != path:
                parents.append(parent)
                path = parent
            return tuple(parents)
