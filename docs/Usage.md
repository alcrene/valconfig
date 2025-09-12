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
    └── defaults.toml
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
    ├── defaults.toml
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
    __default_config_path__ = "defaults.toml"

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
is recommended to specify them in a separate config file `defaults.toml`.[^defaults-name-can-changed] It might look something like the following

```toml
# defaults.toml
data_source   = "<None>"
log_name      = "<None>"
use_gpu       = "False"
n_units       = "3"
connectivites = [[.3, -.3,  .1],
                 [.1,  .1, -.2],
                 [.8,   0, -.2]]
url           = "http://example.com"
```

[^defaults-name-can-change]: The name for defaults file can be changed by defining the class attribute `__default_config_path__` in your `Config` object. It is treated as a relative path, starting from the directory containing the module where your `Config` object is defined. You can set the value to `None` to prevent *ValConfig* from searching for a defaults file.

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

## Updating config values

Because we make `Config` a singleton, the following are two completely equivalent
ways of updating field values.

::::{grid} 2

:::{grid-item-card} By assignment
```python
# main.py
from .config import config  # instance
config.use_gpu = True
```
:::

:::{grid-item-card} By keyword
```python
# main.py
from .config import Config  # class
Config(use_gpu=True)
```
::::

The keyword form can be useful when updating values programmatically.
That said, if you find yourself updating the config programmatically, consider
whether it might not be better to move that logic to a [validator](https://docs.pydantic.dev/latest/concepts/validators) method
of the `Config`.

## User-specific local configuration

In the example above, `data_source`, `use_gpu` and `log_name` are fields that
may be user- or machine-specific. Suppose for example that two people, Jane
and Mary, are using the `BigProject` code in different contexts. Both develop
using their own laptops, but Jane’s project is more data heavy, so she tends to
run her analyses on a bigger workstation. The local configuration on each
machine therefore needs to be slightly different. We can accommodate this by
adding local config files:

::::{card-carousel} 2

:::{card} (Jane, laptop)

```toml
# local.toml
log_name    = "Jane"
use_gpu     = "False"
data_source = "/home/Jane/project-data"
```
:::

:::{card} (Jane, workstation)
```toml
# local.toml
log_name    = "Jane"
use_gpu     = "True"
data_source = "/shared-data/BigProject"
```
:::

:::{card} (Mary, laptop)
```toml
# local.toml
log_name    = "Mary"
use_gpu     = "False"
data_source = 'D:\project-data'
```
:::

::::

We correspondingly add `local.toml` to the file layout

[^local-name-can-change]: The name for local configuration file can be changed by defining the class attribute `__local_config_filename__` in your `Config` object. You can set the value to `None` to prevent *ValConfig* from searching for local config file.

::::{tab-set}

:::{tab-item} Package install
:sync: package-install
```
BigProject
├── .git/
├── __init__.py
├── local.toml
├── main.py
└── config
    ├── __init__.py
    └── defaults.toml
```
:::

:::{tab-item} Inlined-source install
:sync: source-install
```
BigProject
├── .git/
├── __init__.py
├── local.toml
├── main.py
└── config
    ├── __init__.py
    ├── defaults.toml
    └── valconfig.py
```
:::

::::

When `Config` instantiates, it does the following:

1. Check `BigProject/config` for a file named `defaults.toml`.
2. Walk up the directory tree, starting at the _current directory_, until it hits upon a file marking the root of the project. In this case this would be the `.git` file.[^root-filenames]
3. As it recurses up the tree, *ValConfig* keeps track of any `local.toml` file it encounters.
4. Once *ValConfig* has found the project root, it parses (“validates” in Pydantic parlance) all configuration values at once, with the following order of precedence:
   1. Keyword arguments passed directly to the `Config(…)` call
   2. Values defined in local configuration files.
      If there are many such files, those at _deeper_ levels of the hierarchy (so closest to the current working directory) have _higher_ precedence.
   3. Values defined in the defaults configuration file.
   4. Default values defined in the `Config` class definition.


:::{hint} We can think of repositories as being used either as a “project” or
a “library”, with library repositories being _imported_ by projects. 
Typically a user-local config file is useful for project repositories.
:::



[^root-filenames]: By default, the files indicating a project root are `.git`, `.hg`, `.smt`, `pyproject.toml`,
  `setup.cfg`, `setup.py` and `poetry.lock`. This can be changed by overriding the class attribute `__projectroot_filenames__`.
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
- `<PROJECTROOT>`: In `Path` type fields, this will be substituted by the identified project root. A dollar sign `$` can also be used for the same effect.
  ```toml
  path1 = "<PROJECTROOT>/this/path/is/relative/to/project/root"
  path2 = "$/so/is/this/one"
  ```
- `<default>`: Scan the sources for a value in _reverse_ order of their precedence, so that defaults defined in the `BaseModel` or `defaults.toml` are preferred.
  Can be used to unset an option from another config file.

To add your own substitutions, define the dictionary `__sentinel_substitutions__`
in your `Config` subclass:

```python
class Config(ValConfig):
  __sentinel_substitutions__: ClassVar = ValConfig | {"<SITEURL>": "https://ourcompany.com"}
```

## Relative path resolution

We apply the following rules to fields of type `Path`

- Absolute paths are never be modified.
- Relative paths loaded from a **config file** can have three different anchors:
  + A path with no prefix, like `relative/to/file`, is relative to the **config file**.
  + A path with a dot prefix, like `./relative/to/cwd`, is relative to the **current directory**.
  + A path with the special marker `<PROJECTROOT>/root_file` is relative to the **project root**.
    The shorthand `$/root_file` can also be used for a path relative to the project root.
- Relative paths set directly on the Config object are not associated to a config file;
  these are always relative to the **current directory**.

Note that the project root is not automatically expanded: it works exactly like the home directory markers.
To fully expand a path, use ``path.expandprojectroot()``.

:::{important}
For this logic to apply, the annotation type of a field must be either `Path` `Optional[Path]` or `Path | None`.
If it has other type, e.g. `Path | str` or `Annotated[Path]`, it will not be recognized as a Path field and no special logic will be applied.

Paths to which *ValConfig* has applied the logic above will appear as type `ConfigPath` in the validated config object.
:::



## Hierarchical fields

TODO: Side-by-side cards

## Extending a configuration / Configuration templates

TODO: Example: add a field to `contrib.FiguresConfig`

<!-- ## Config class options

The behaviour of a `ValConfig` subclass can be customized by setting class
variables. Three have already introduced: `__default_config_path__`, 
`__local_config_filename__`, `__value_substitutions__`. The full list is as follows:

`__default_config_path__`
: Path to the config file containing defaults.
  Path is relative to the directory defining the `Config` class (in our example,
  path is relative to *config/*)

`__local_config_filename__`
: Filename to search for local configuration. If `None`, no search is performed.
  Typically this is set to `None` for library packages and a string value
  for project packages: library packages are best configured by
  modifying their `config` object (perhaps within a project’s own `config`),
  than by using a local file.
  If no file is found, and `__create_template_config__` is `True` (the default),
  then a blank config file with instructions is created at the root of the project repository.
  Default value is `None`. 

`__value_substitutions__`
: Dictionary of substitutions for plain text values.
  Substitutions are applied before other validators, so they can be used to
  convert invalid values to valid ones, or to avoid interpreting the value
  as a string.

`__create_template_config__`
: Whether a template config file should be created in a standard location when
  no local config file is found. This has no effect when `__local_config_filename__`
  is `None`.
  The default is `True`, which is equivalent to letting `__local_config_filename__`
  determine whether to create a template config. In almost all cases this default
  should suffice.
  Typically this is set to `False` for utility
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
 -->

(validators)=
## Advanced usage: adding logic with validators

Since a `Config` class is a normal class, you can all the usual Python functionality
to add arbitrary logic, like overriding `__init__` or adding computed fields
via properties:

```python
from valconfig import ValConfig
from pathlib import Path
from typing import Optional

class Config(ValConfig):
  data_source: Optional[Path]
  log_name: Optional[str]
  use_gpu: bool

  def __init__(self, **kwds):
    kwds["use_gpu"] = False   # Modify `kwds` before fields are assigned
    super().__init__(**kwds)  # <-- Fields are assigned & validators are run here
    self.use_gpu = False      # Modify fields after they have been assigned

  @property
  def log_header(self):
    return f"{self.logname} ({self.data_source})"
```

However there should be little use in overriding `__init__`, since *Pydantic*
provides *validators* which can be used to assign arbitrary logic to a field:

```python
import torch
from pydantic import validator
from valconfig import ValConfig

class Config(ValConfig):
  use_gpu: bool

  @validator("use_gpu", mode="after")
  @classmethod
  def check_gpu(self, v):
    if v and not torch.has_cuda:
      print("Cannot use GPU: torch reports CUDA is not available.")
      v = False
    return v
```

The `"after"` model indicates to run the validator after a value has been cast to its target prescribed type. To run a validator before type casting, use the `"before"` mode:

```python
from pathlib import Path
from valconfig import ValConfig
from typing import Optional

class Config(ValConfig):
  tokens: frozenset 

  @validator("data_source", mode="before"):
  @classmethod
  def default_source(cls, tks):
    return [tk for tk in _tks if not tk.startswith("private_")]
      # Because we use mode="before", we don’t need to cast to frozenset
  ```

There is a lot more one can do with validators, as detailed in [Pydantic’s documentation](https://docs.pydantic.dev/latest/concepts/validators/).