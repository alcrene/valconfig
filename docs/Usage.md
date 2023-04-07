# Usage

## Basic usage

We suggest organizing a project with the following file layout:

::::{tab-set}

:::{tab-item} Package install
:sync: package-install
```
BigProject
├── .git/
├── __init__.py
├── main.py
└── config
    ├── __init__.py
    └── defaults.cfg
```
:::

:::{tab-item} Inlined-source install
:sync: source-install
```
BigProject
├── .git/
├── __init__.py
├── main.py
└── config
    ├── __init__.py
    ├── defaults.cfg
    └── valconfig.py
```
:::

::::

Here the `Config` class is defined inside a module `__init__.py`,
so that it can be placed alongside a configuration file and still imported from `config`:

```python
# main.py
from .config import config

...
result = urlopen(config.url) 
```

::::{tab-set}

:::{tab-item} Package install
:sync: package-install

```python
# config/__init__.py
from valconfig import ValConfig   # This line changes between package and source install

from pathlib import Path
from typing import Optional
from pydantic import HttpUrl
from scityping.numpy import Array

class Config(ValConfig):
    __default_config_path__ = "defaults.cfg"

    data_source: Optional[Path]
    log_name: Optional[str]
    use_gpu: bool
    url: HttpUrl
    n_units: int
    connectivites: Array[float, 2]  # 2D array of floats

config = Config()
```
:::

:::{tab-item} Inlined-source install
:sync: source-install

```python
# config/__init__.py
from .valconfig import ValConfig   # This line changes between package and source install

from pathlib import Path
from typing import Optional
from pydantic import HttpUrl
from scityping.numpy import Array

class Config(ValConfig):
    __default_config_path__ = "defaults.cfg"

    data_source: Optional[Path]
    log_name: Optional[str]
    use_gpu: bool
    url: HttpUrl
    n_units: int
    connectivites: Array[float, 2]  # 2D array of floats

config = Config()
```
:::

::::

Defaults can be specified directly in the `Config` class, but when possible it
is recommended to specify them in a separate config file, which in this example
we named `defaults.cfg`. It might look something like the following

```
# defaults.cfg
[DEFAULTS]

data_source   = <None>
log_name      = <None>
use_gpu       = False
n_units       = 3
connectivites = [[.3, -.3,  .1],
                 [.1,  .1, -.2],
                 [.8,   0, -.2]]
url           = example.com
```

The path to this file is specified by defining the class variable `__default_config_path__`. When this variable is undefined or `None`,
`Valconfig` presumes that no such file exists.

:::{Important}
Your `Config` class should be instantiable without arguments, as
`Config()`. This means that all parameters should have defaults, either in
the class itself, or in a defaults file.
:::


Finally, it is often convenient to have `config` available at the top level
of the package. For this we add an import to the root `__init__.py` file.

```python
# __init__.py
from .config import config
```

## User-specific local configuration

## Hierarchical configuration / multiple files

In the example above, `data_source`, `use_gpu` and `log_name` are fields that
may be user- or machine-specific. Suppose for example that two people, Jane
and Mary, are using the `BigProject` code in different contexts. Both develop
using their own laptops, but Jane’s project is more data heavy, so she tends to
run her analyses on a bigger workstation. The local configuration on each
machine therefore needs to be slightly different. We can accommodate this by
adding local config files:

::::{card-carousel} 2

:::{card} (Jane, laptop)

```
# local.cfg
[DEFAULTS]
log_name    = Jane
use_gpu     = False
data_source = /home/Jane/project-data
```
:::

:::{card} (Jane, workstation)
```
# local.cfg
[DEFAULTS]
log_name    = Jane
use_gpu     = True
data_source = /shared-data/BigProject
```
:::

:::{card} (Mary, laptop)
```
# local.cfg
[DEFAULTS]
log_name    = Mary
use_gpu     = False
data_source = D:\project-data
```
:::

::::

We correspondingly add `local.cfg` to the file layout and the `Config` definition:

::::{grid} 1 1 2 2

:::{grid-item-card} File layout
:columns: auto
```
BigProject
├── .git/
├── __init__.py
├── local.cfg
├── main.py
└── config
    ├── __init__.py
    ├── defaults.cfg
    └── valconfig.py
```
:::

:::{grid-item-card} `Config definition`
:columns: auto

```python
# config/__init__.py
from valconfig import ValConfig

from pathlib import Path
from typing import Optional
from pydantic import HttpUrl
from scityping.numpy import Array

class Config(ValConfig):
    __default_config_path__ = "defaults.cfg"
    __local_config_filename__ = "local.cfg"

    data_source: Optional[Path]
    log_name: Optional[str]
    use_gpu: bool
    url: HttpUrl
    n_units: int
    connectivites: Array[float, 2]

config = Config()
```
:::

::::

When `Config` instantiates, it does the following:

1. Parse the file at the location pointed to by `__default_config_path__` and
   instantiate the `config` instance.
2. Search the current directory for a file matching `__local_config_filename__`.  
   If one is found, it is parsed and `config` updated.
3. Move up the directory tree and search again for a file matching `__local_config_filename__`.  
   `ValConfig` will continue moving up the directory tree until it hits the root directory.[^multiple-local-configs]

 In our example, to find `local.cfg`, the project would need to be executed from
 within `BigProject` or one of its subdirectories.

:::{hint} We can think of repositories as being used either as a “project” or
a “library” – where library repositories are *imported* by projects. 
Typically a user-local config file is useful for project repositories.
:::


[^multiple-local-configs]: In fact, the search up the directory tree continues
  until we hit the root directory. Then all the found config files are parsed
  in *reversed* order, and the `config` instance updated with each. This allows
  a master file to define defaults, with more specific config files for
  subprojects. We expect however, that in most cases a single local config
  file to be enough.

## Special value substitutions

Config files are typically parsed as text, which leaves it up to the `Config`
class to define validators which correctly interpret those values. To avoid
having to write custom validators for some common cases, the following special
values are provided:

- `<None>`: Converted to `None`.
- `<default>`: Use the default defined in the `BaseModel`. Can be used to
  unset an option from another config file.

To add your own substitutions, update the dictionary `__value_subsitutions__`
in your `Config` subclass.

## Relative path resolution

When a value, after validation, is an instance of {py:class}`~python:pathlib.Path`, then it is resolved with the following rules:
- If the path is absolute (i.e. it starts with `/`), it is not changed.
- If the path is relative, it is prepended with the directory in which it was defined.
  For example, if the file `~/my-projects/projectA/local.cfg` defines the path
  ```
  "../data/"
  ```
  it will be resolved to
  ```
  "~/my-projects/data/"
  ```

## Config class options

The behaviour of a `ValConfig` subclass can be customized by setting class
variables. Three have already introduced: `__default_config_path__`, 
`__local_config_filename__`, `__value_substitutions__`. The full list is as follows:

`__default_config_path__`
: Path to the config file containing defaults.
  Path is relative to the directory defining the `Config` class (in our example,
  path is relative to *config/*)

`__local_config_filename__`
: Filename to search for local configuration.
  If no file is found, and `__create_template_config__` is `True`, then a blank
  config file with instructions is created at the root of the project repository.

`__value_substitutions__`
: Dictionary of substitutions for plain text values.
  Substitutions are applied before other validators, so they can be used to
  convert invalid values to valid ones, or to avoid interpreting the value
  as a string.

`__create_template_config__`
: Set to `True` if you want a template config
  file to be created in a standard location when no user config file is
  found. Default is `False`. Typically this is set to `False` for utility
  packages, and `True` for project packages.

`__interpolation__`
: Passed as argument to {py:class}`~python:configparser.ConfigParser`.
  Default is {py:class}`~python:configparser.ExtendedInterpolation`.
  (Note that, as with {py:class}`~python:configparser.ConfigParser`, an *instance* must be passed.)

`__empty_lines_in_values__`
: Passed as argument to `ConfigParser`.
  Default is `True`: this prevents multiline values with empty lines, but
  makes it much easier to indent without accidentally concatenating values.

`__top_message_default__`
: The instruction message added to the top of a
  template config file when it is created.
