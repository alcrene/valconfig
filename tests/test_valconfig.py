import sys
import pytest
from pathlib import Path
import valconfig
from pydantic import HttpUrl

# Ensure the directory containing the current file is in Path, so we can load BigProject
sys.path.insert(0, str(Path(__file__).parent))

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

def test_singleton():
    from BigProject.config import config, Config

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
