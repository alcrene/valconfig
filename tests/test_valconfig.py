import pytest
from pathlib import Path
import valconfig

# FIXME: For some reason, when pytest runs this file, it cannot find the 
# `valconfig` package, even when it is installed.
# So instead we call the test function at the end of the module, and
# execute it with Python.

def test_usage_example():
    from BigProject import config

    # Values from packaged defaults
    assert config.prefix is None
    assert config.n_units == 3
    assert config.url == "http://example.com"

    # Values overridden by local.cfg
    assert config.log_name == "Jane"
    assert config.use_gpu == True
    # The data_source path in local.cfg is relative, so it is resolved relative
    assert config.data_source == Path(__file__).parent/"shared-data/BigProject"
    assert config.tmp_dir == Path("/tmp")

test_usage_example()