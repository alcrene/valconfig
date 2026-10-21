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
