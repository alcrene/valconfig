from valconfig import ValConfig

from pathlib import Path
from typing import Optional
from pydantic import HttpUrl
# from scityping.numpy import Array

class Config(ValConfig):
    data_source: Optional[Path]   # Relative path in local config
    default_data_source: Optional[Path] # Relative input path in default config
    out_dir: Optional[Path]       # Relative output path in default config
    err_dump_path: Optional[Path] # "." path in default config -> treated as output path
    tmp_dir: Optional[Path]       # Absolute path in local config
    prefix: Optional[str]         # Initialized with None
    log_name: Optional[str]
    use_gpu: bool                 # Default overriden by local
    url: HttpUrl
    n_units: int
    #connectivities: Array[float, 2]  # 2D array of floats


config = Config()