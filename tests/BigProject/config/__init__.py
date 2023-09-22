from valconfig import ValConfig

from pathlib import Path
from typing import Optional
try:
    from pydantic.v1 import HttpUrl
except ModuleNotFoundError:
    from pydantic import HttpUrl
# from scityping.numpy import Array

class Config(ValConfig):
    __default_config_path__ = "defaults.cfg"
    __local_config_filename__ = "local.cfg"

    data_source: Optional[Path]   # Relative path in local config
    default_data_source: Optional[Path] # Relative input path in default config
    out_dir: Optional[Path]       # Relative output path in default config
    err_dump_path: Optional[Path] # "." path in default config -> treated as output path
    tmp_dir: Optional[Path]       # Absolute path in local config
    prefix: Optional[str]         # Initialized with None
    log_name: Optional[str]
    use_gpu: bool
    url: HttpUrl
    n_units: int
    #connectivites: Array[float, 2]  # 2D array of floats


config = Config()