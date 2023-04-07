from valconfig import ValConfig

from pathlib import Path
from typing import Optional
from pydantic import HttpUrl
# from scityping.numpy import Array

class Config(ValConfig):
    __default_config_path__ = "defaults.cfg"
    __local_config_filename__ = "local.cfg"

    data_source: Optional[Path]   # Used to test relative path
    tmp_dir: Optional[Path]       # Used to test absolute path
    prefix: Optional[str]         # Used to test initializing with None
    log_name: Optional[str]
    use_gpu: bool
    url: HttpUrl
    n_units: int
    #connectivites: Array[float, 2]  # 2D array of floats


config = Config()