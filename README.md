# Validating config

Simple, extendable configuration objects

## Quick start

### Installation

As a *package*:

- ```bash
  pip install valconfig
  ```

Or as *inlined source*:
- Copy the `valconfig.py` file into your project and install [Pydantic](https://pydantic-docs.helpmanual.io/).

### Example usage

```python
# config.py
from valconfig import ValConfig
from pydantic import HttpUrl
from scityping.numpy import Array

class Config(ValConfig):
    n_units: int=5
    connectivites: Array[float, 2]  # 2D array of floats
    url: HttpUrl="example.com"

config = Config()
```

For more detailed usage, see the [documentation](https://valconfig.readthedocs.io/en/stable/usage.html).

## Motivation

Many types of projects make use of some system to set configuration options,
and while the type of project may influence that system, its basic requirements
are pretty much always the same:

- It should be easy to read.
- It should be easy to extend.

*Validating config* came about to fulfill these needs for scientific programming,
which is a bit of an extreme case: On the one hand, scientists are not professional programmers,
so the system needs to be so simple that it needs no documentation at all.
On the other hand, they are also constantly developing new methods, and so
also need to be able to add new configuration options and new variable types.
Moreover, most users are also possible contributors. We therefore need to allow
them to set local configuration options without breaking others’ config, and without
requiring anything more complicated than an `git push`. (Local configuration
may include whether to use a GPU, where to save data / figures, MPI flags, etc.)

Thus we needed a way to
- Set version-controlled defaults, that are packaged with the repository.
- Make it easy to know what the configurable options are.
- Make it easy to change those options, without touching the defaults.

In addition, projects often depend on other projects, so we need a way to set
*their* options as well.

Finally, not all parameters are strings or simple numerical values. Some might need to
be cast to NumPy arrays; others might need to be pre-processed, or checked for
consistency with other parameters, or simply inferred from other parameters.
These are all roles that conceptually belong in a configuration parser.
As scientist programmers, we already have the bad habit of mixing up all their logic –
let’s give ourselves one less reason to do so.

This adds two additional desiderata:

- Support for composition: Have one configuration for multiple packages.
- Validation of values based on provided type information.

## What a *ValidatingConfig* provides

- A mechanism to define simple lists of configuration options with *zero boilerplate*:
  just list the parameter names, their types, and optionally their default.
- *Built-in validation* provided by [Pydantic](https://pydantic-docs.helpmanual.io/).
- Additional validation for *scientific types* available with [scitying](https://scityping.readthedocs.io/).
- An optional mechanism to autogenerate a file for users’ local configuration,
  with usage instructions embedded in the file.
- The ability to *compose* configuration objects from multiple packages into a
  single main configuration – *even when those packages don’t use* ValidatingConfig.
- The ability to *extend* the functionality of a config object with all the
  functionality Python has to offer: read environment variables with `os.getenv`,
  get command line parameters with `sys.argv`, etc.
  + Other packages typically need to add features like these because their config objects are
    more limited. We avoid this by defining `config` with a standard class.
    This keeps this package lean, and your code simple.

Other features

- Zero onboarding:
    + Uses only standard Python: No custom function calls, no boilerplate.
      If you know modern Python, you already know how to use this module.
    + Just define a `Config` class with the parameter names and their types.
    + Use the `Config` class as any other Python class.
- Define your own custom types with either *Pydantic* or *Scityping*. [^new-types]
- *Pydantic* provides [validators](https://docs.pydantic.dev/usage/validators/) which can be used to add per-field
  validation and pre-processing. These are defined with plain Python,
  not some minilanguage or a sanitized `eval`.
- Use standard [properties](https://docs.python.org/3/library/functions.html?highlight=property#property) to define computed (inferred) values.
- Use any file format
    + The default uses stdlib’s `configparser`, but you can override the method
      used to read files.
- Relative paths in config files are correctly resolved.
- Automatically finds the local configuration file
    + Just set the class variable `__local_config_filename__`, and `ValConfig`
      will recurse up the directory tree until it finds a matching file.
    + This is especially convenient to accommodate multiple users who organize
      their work differently.
- Hierarchical: Organize your parameters into categories by defining nested classes.

  ```python
  from valconfig import ValConfig

  class Config(ValConfig):

    class figures:
      width: float
      format: str
      class curves:
        colormap: str | list[str]
      class heatmaps:
        colormap: str | list[str]

    class run:
      cache: bool

    class model:
      n_units: int
  ```


- Composable
    + Want multiple config objects for each of your projects subpackage ?
      Just import them.
    + Want to combine them into a single root config file ?
      Just import them.

      ```python
      from valconfig import ValConfig
      from .subpkg1 import config as config1
      from .subpkg2 import config as config2

      class Config(ValConfig):
        pkg1: config1
        pkg2: config2
      ```

    + Does your project depend on another ?
      Define the parameters you need to modify and add a function which updates
      the config with those parameters.

      ```python
      from valconfig import ValConfig
      from other_package import config as other_config

      class Config(ValConfig):
        # List the parameters you want to modify
        other_package_option1: int
        other_package_option2: float
        # Include the 3rd party config
        other_package: other_config

        @validator("other_package")
        def update_other_package_options(cls, other_config, values):
          # The exact details here will depend on the 3rd party package
          other_config.opt1 = values["other_package_option1"]
          other_config.opt2 = values["other_package_option2"]
      ```

[^new-types]: *Scityping* was developed as an extension of *Pydantic* to allow
the use of (abstract) base classes in type definitions, for example defining
a field of type `Model` which accepts any subclass of `Model`. (In plain
Pydantic values are always *coerced* to the target type.) Whether it is best
to define new types with either *Scityping* or *Pydantic* largely depends on
whether this use as abstract classes is needed.

## In relation to other projects

What’s wrong with the gazillion other config file projects out there ?
Why not use one of those ?

In short, because most of these packages were developed many years ago, before
the standardization of type annotations. The can all perform the basic task of
converting a file to a Python dictionary of strings, but fulfilling all of our
aforementioned desiderata was difficult without creating a bloated package.
Understandly therefore, they focused on the features required by their own use
cases, which means that I found them all unsatisfactory in some respect:

- Some introduce a new API with custom functions or decorators to define parameters. This makes it more difficult to learn and extend. ([vyper-config](https://github.com/alexferl/vyper), [hydra](https://hydra.cc/docs/intro/))
- Many provide no validation ([one-config](https://pypi.org/project/one-config/), [config2](https://github.com/grimen/python-config2)).
- When validations functions are provided, the target type is often not specified
  by the config object, but in the calling code – if your configuration library is allows to define
  the *name* but not the *type* of the parameters, that’s only 50% of the information and 20% of the work.
  ([configparser](https://docs.python.org/3/library/configparser.html), [vyper-config](https://github.com/alexferl/vyper))
- For the examples I know which provides validation at the config level,
  the set of supported types is very limited and basically hard-coded. ([OmegaConf](https://omegaconf.readthedocs.io/en/latest/structured_config.html), [CFG API](https://docs.red-dove.com/cfg/python.html))
- Some approaches even define their own file formats, substantially raising the barrier to adoption. ([CFG API](https://docs.red-dove.com/cfg/python.html))

With the standardization of type annotations in Python 3.6–3.8, and the availability of classes like [Pydantic](https://pydantic-docs.helpmanual.io/)’s `BaseModel`, defining classes with validation
logic has become a breeze, and converting a `BaseModel` into a full-featured
config parser basically only needs two things:

- functionality for reading values from files;
- ability to compose configuration classes.

In effect therefore, `ValConfig` is just a subclass of `BaseModel` with some
simple methods for reading config files. The biggest difference is that each
subclass of `ValConfig` is made a *singleton*. We use this pattern for exactly
the same reasons as [one-config](https://pypi.org/project/one-config/): it
solves a host of corner cases, makes it trivial to support composing configs,
and ensures that config objects are a single source of truth.

By relying on Pydantic, `ValConfig` can be extremely lean, while still providing
functionality that is on-par with the much heavier packages listed above.
Pydantic itself is highly mature and actively maintained.

> The `ValConfig` class and all its utility functions clock in at less than
> 500 lines of code and are contained in a single, easily maintained module. If
> desired, the module can even be included as part of your project’s source
> code, thus removing *valconfig* as package dependency and giving you
> full control over the config object.

Finally, *using ValConfig does not preclude from using another config parser*.
Indeed, the provided implementation uses `configparser` to parse files mostly
because it is already installed part of the standard library. The execution flow
is basically

1. Read config file(s) with `configparser`.
2. Validate with `Pydantic`.

To use a different config parser, just subclass `ValConfig` and override the
the method `read_cfg_file()`.
