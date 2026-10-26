import sys
import pytest
from pathlib import Path
from typing import Optional
import valconfig
from pydantic import HttpUrl

def test_usage_example():
    from BigProject import config

    # Values from packaged defaults
    assert config.prefix is None
    assert config.n_units == 3
    assert config.url == HttpUrl("http://example.com")

    # Values overridden by local.cfg
    assert config.log_name == "Jane"
    assert config.use_gpu == True
    # The data_source path in local.cfg is relative, so it is resolved relative
    project_root = Path(__file__).parent
    default_root = Path(sys.modules[config.__module__].__file__).parent

    assert config.data_source.expandprojectroot().resolve()         == project_root/"shared-data/BigProject"
    assert config.default_data_source.expandprojectroot().resolve() == default_root/"wordlist.txt"
    assert config.out_dir.expandprojectroot().resolve()             == project_root/"output.dat"
    assert config.err_dump_path.expandprojectroot().resolve()       == project_root
    assert config.tmp_dir.expandprojectroot().resolve()             == Path("/tmp")

# test_usage_example()

def test_singleton(monkeypatch):
    from BigProject.config import config, Config
    # Config is a session-wide singleton: restore `n_units` afterwards so other tests see the default
    monkeypatch.setattr(config, "n_units", config.n_units)

    conf2 = Config()
    conf3 = Config(n_units=10)

    assert config is conf2 is conf3
    assert config.n_units == 10


def test_default_marker():
    from pydantic import Field, ValidationError
    from valconfig.valconfig import NestedValConfig  # Doesn't search for config files

    class Config1(NestedValConfig):
        a: int = 3
        b: list[int] = Field(default_factory=lambda: [1, 2])
    config1 = Config1(a="<DEFAULT>", b="<DEFAULT>")
    assert config1.a == 3
    assert config1.b == [1, 2]

    # No default anywhere => error
    class Config2(NestedValConfig):
        a: int
    with pytest.raises(ValidationError, match="no default value is defined"):
        Config2(a="<DEFAULT>")

def test_class_valued_attribute():
    """An annotated attribute whose value is a class must not be converted into a nested config."""
    from typing import ClassVar
    from valconfig.valconfig import NestedValConfig

    class Config(NestedValConfig):
        n: int = 1
        container: ClassVar[type] = dict
        sequence: ClassVar[type] = list
        class section:
            m: int = 2

    assert Config.container is dict
    assert Config.sequence is list
    assert set(Config.model_fields) == {"n", "section"}  # Bare nested classes are still converted
    assert Config().section.m == 2

def test_path_annotations():
    """`Path` and `Optional[Path]` annotations are converted to `ConfigPath`, including in nested sections."""
    # NB: String annotations are evaluated in the module globals, so `Optional` is imported at the top
    from valconfig.valconfig import NestedValConfig, ConfigPath

    class Config(NestedValConfig):
        p: Path = Path("a")
        q: Optional[Path] = None
        s: "Optional[Path]" = None   # Explicit string annotation
        class section:
            r: Path = Path("b")

    assert Config.model_fields["p"].annotation is ConfigPath
    assert Config.model_fields["q"].annotation == ConfigPath | None
    assert Config.model_fields["s"].annotation == ConfigPath | None
    assert Config.sectionType.model_fields["r"].annotation is ConfigPath
    config = Config(q="c")
    assert type(config.p) is type(config.q) is type(config.section.r) is ConfigPath

def test_forward_reference():
    """Annotations may refer to types which are only defined after the config class."""
    from valconfig.valconfig import NestedValConfig

    class Config(NestedValConfig):
        later: "Later"
    class Later(NestedValConfig):
        x: int = 0
    Config.model_rebuild()

    assert Config(later={"x": 2}).later.x == 2

def test_future_annotations():
    """With `from __future__ import annotations`, annotations are strings: they must be handled the same way."""
    from valconfig.valconfig import ConfigPath
    from future_annotations_config import Config

    assert Config.model_fields["p"].annotation is ConfigPath
    assert Config.sectionType.model_fields["r"].annotation is ConfigPath
    config = Config(later={"x": 2}, section={"n": 5})
    assert config.later.x == 2
    assert config.section.n == 5
    assert type(config.p) is type(config.section.r) is ConfigPath

def test_future_annotations_path_spellings():
    """With `from __future__ import annotations`, all spellings of an optional Path are recognized."""
    from valconfig.valconfig import ConfigPath
    from future_annotations_config import Config

    for nm in ["q", "s", "t", "v"]:
        assert Config.model_fields[nm].annotation == ConfigPath | None, nm
    assert Config.model_fields["u"].annotation is ConfigPath
    assert Config.model_fields["n"].metadata  # Non-Path annotations are left to Pydantic
    config = Config(q="q", s="s", t="t")
    assert all(type(getattr(config, nm)) is ConfigPath for nm in ["q", "s", "t", "u"])

def test_nested_types_in_annotations():
    """Nested classes used in annotations (possibly inside generics) are types, not sections."""
    from pydantic import BaseModel
    from valconfig.valconfig import NestedValConfig
    from future_annotations_config import TypedNested as FutureConfig

    class Config(NestedValConfig):
        class Sub(BaseModel):
            x: int = 0
        class Item(BaseModel):
            x: int = 0
        sub: Sub
        opt: Optional[Sub] = None
        items: list[Item] = []
        class section:
            n: int = 1

    for cls in (Config, FutureConfig):  # Without and with `from __future__ import annotations`
        assert set(cls.model_fields) == {"sub", "opt", "items", "section"}, cls.__module__
        config = cls(sub={"x": 1}, items=[{"x": 2}])
        assert config.sub.x == 1 and config.items[0].x == 2 and config.section.n == 1

def test_nested_context(tmp_path):
    """Nested sections must look up sources and defaults within their own section."""
    from typing import ClassVar
    from pathlib import Path
    from valconfig.valconfig import ValConfig, SourcedDeepChainMap

    (tmp_path/"sub").mkdir()
    defaults = {"n": 1, "section": {"n": 7, "data": "rel/data"}}
    local = {"section": {"n": "<DEFAULT>"}}

    class Config(ValConfig):
        __default_config_path__: ClassVar = None
        __local_config_filename__: ClassVar = None
        n: int
        class section:
            n: int
            data: Path
        @classmethod
        def load_config_files(cls):
            return SourcedDeepChainMap(local, defaults, sources=(tmp_path/"sub"/"local.toml", tmp_path/"defaults.toml")), tmp_path

    config = Config()
    assert config.n == 1
    assert config.section.n == 7  # Not the top-level `n`
    # Relative path is anchored to the directory of the file which defines it
    assert config.section.data == tmp_path/"rel/data"

def test_get_source(tmp_path):
    from typing import ClassVar, Optional
    from valconfig.valconfig import ValConfig, NestedValConfig, SourcedDeepChainMap, KWARGS

    defaults_path, local_path = tmp_path/"defaults.toml", tmp_path/"local.toml"
    defaults = {"a": 1, "b": 2, "c": 3, "label": "<None>",
                "section": {"x": 10, "y": 20}}
    local = {"b": 5, "c": "<DEFAULT>",
             "section": {"y": "<DEFAULT>"}}

    class OtherConfig(NestedValConfig):  # Instantiated separately, as if imported from another package
        level: int = 0
    OtherConfig(level=4)

    class Config(ValConfig):
        __default_config_path__: ClassVar = None
        __local_config_filename__: ClassVar = None
        a: int
        b: int
        c: int = 0
        d: int = 7
        e: int
        label: Optional[str]
        other: OtherConfig
        class section:
            x: int
            y: int
        @classmethod
        def load_config_files(cls):
            return SourcedDeepChainMap(local, defaults, sources=(local_path, defaults_path)), tmp_path

    config = Config(e=9)
    assert config.get_source("a") == defaults_path
    assert config.get_source("b") == local_path
    assert config.c == 0 and config.get_source("c") is None          # <DEFAULT> -> class default
    assert config.get_source("d") is None                              # Class default
    assert config.get_source("e") is KWARGS
    assert config.label is None and config.get_source("label") == defaults_path  # Sentinel substitution keeps its source
    assert config.get_source("section", "x") == defaults_path
    assert config.section.y == 20 and config.get_source("section", "y") == defaults_path  # <DEFAULT> -> lowest precedence
    assert config.other.level == 4 and config.get_source("other", "level") is KWARGS  # From OtherConfig's own data

def test_find_projectroot(tmp_path):
    from valconfig import find_projectroot
    (tmp_path/"pyproject.toml").touch()
    (tmp_path/"a"/"b").mkdir(parents=True)
    (tmp_path/"local.toml").touch()
    (tmp_path/"a"/"b"/"local.toml").touch()
    root, local_paths = find_projectroot(tmp_path/"a"/"b", local_filename="local.toml")
    assert root == tmp_path
    assert local_paths == [tmp_path/"a"/"b"/"local.toml", tmp_path/"local.toml"]
    assert find_projectroot(tmp_path/"a", root_filenames={"nothing"})[0] is None

def test_configpath_anchors():
    """Relative paths are anchored to `anchor_dir`, except those starting with './', '~' or a project root marker."""
    from valconfig.valconfig import ConfigPath

    assert ConfigPath("a/b", anchor_dir="/cfg") == Path("/cfg/a/b")
    assert ConfigPath("./a/b", anchor_dir="/cfg") == Path("a/b")   # Relative to CWD
    assert ConfigPath(".", anchor_dir="/cfg") == Path(".")
    assert ConfigPath("~/a", anchor_dir="/cfg") == Path("~/a")
    assert ConfigPath("$/a", anchor_dir="/cfg") == Path("$/a")
    assert ConfigPath("<PROJECTROOT>/a", anchor_dir="/cfg") == Path("<PROJECTROOT>/a")
    assert ConfigPath("/abs/a", anchor_dir="/cfg") == Path("/abs/a")
    assert ConfigPath("a/b") == Path("a/b")

def test_configpath_relative_to_cwd(tmp_path):
    """In a config file, a path starting with './' is relative to the current directory, not to the file."""
    from typing import ClassVar
    from valconfig.valconfig import ValConfig, SourcedDeepChainMap

    local = {"to_file": "rel/data", "to_cwd": "./rel/data"}

    class Config(ValConfig):
        __default_config_path__: ClassVar = None
        __local_config_filename__: ClassVar = None
        to_file: Path
        to_cwd: Path
        @classmethod
        def load_config_files(cls):
            return SourcedDeepChainMap(local, sources=(tmp_path/"local.toml",)), tmp_path

    config = Config()
    assert config.to_file == tmp_path/"rel/data"
    assert config.to_cwd == Path("rel/data")

def test_expandprojectroot_arguments():
    """The `projectroot` and `projectrootmarkers` arguments override the path’s own values."""
    from valconfig.valconfig import ConfigPath

    path = ConfigPath("$/a", projectroot="/proj")
    assert path.expandprojectroot() == Path("/proj/a")
    assert path.expandprojectroot(projectroot="/other") == Path("/other/a")
    assert ConfigPath("$/a").expandprojectroot(projectroot="/proj") == Path("/proj/a")

    path = ConfigPath("@root/a", projectroot="/proj")
    assert path.expandprojectroot(projectrootmarkers={"@root"}) == Path("/proj/a")
    assert path.expandprojectroot() == Path("@root/a")   # Not a default marker
    # Overriding the markers replaces the defaults
    assert ConfigPath("$/a", projectroot="/proj").expandprojectroot(projectrootmarkers={"@root"}) == Path("$/a")

def test_configpath_derived_paths(tmp_path):
    """Every path derived from a ConfigPath is a ConfigPath with the same project root.
    (On Python < 3.12, this relies on the backport in `valconfig._pathlib_compat`.)"""
    import pickle
    from valconfig.valconfig import ConfigPath

    (tmp_path/"sub").mkdir()
    (tmp_path/"sub"/"f.txt").touch()
    path = ConfigPath(tmp_path/"sub", projectroot="/proj")
    rel = ConfigPath("a/b.txt", projectroot="/proj")
    derived = {
        "truediv": path / "f.txt", "rtruediv": "/x" / rel, "joinpath": path.joinpath("a", "b"),
        "parent": path.parent, "parents[0]": path.parents[0], "parents[-1]": path.parents[-1],
        "with_name": rel.with_name("c"), "with_suffix": rel.with_suffix(".md"), "with_stem": rel.with_stem("c"),
        "relative_to": path.relative_to(tmp_path), "absolute": rel.absolute(), "resolve": rel.resolve(),
        "expanduser": ConfigPath("~/a", projectroot="/proj").expanduser(),
        "iterdir": next(path.iterdir()), "glob": next(path.glob("*.txt")),
        "expandprojectroot": ConfigPath("$/a", projectroot="/proj").expandprojectroot(),
    }
    for name, p in derived.items():
        assert type(p) is ConfigPath, name
        assert p.projectroot == "/proj", name

    assert isinstance(path, Path)
    assert path == Path(tmp_path/"sub") and hash(path) == hash(Path(tmp_path/"sub"))
    assert str(rel) == "a/b.txt" and rel.parts == ("a", "b.txt")
    assert list(path.parents) == list(Path(tmp_path/"sub").parents)
    assert type(ConfigPath.cwd()) is ConfigPath
    assert pickle.loads(pickle.dumps(rel)) == rel
