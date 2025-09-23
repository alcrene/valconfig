# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
A base class for project config objects

For a package called `MyPackage`, the following files should be defined:

    MyPackage/MyPackage/config/__init__.py
    MyPackage/MyPackage/config/defaults.toml
    MyPackage/local.toml

Within MyPackage/MyPackage/config/__init__.py, one then does something like

    from pathlib import Path
    from valconfig import ValConfig

    class Config(ValConfig):
        class paths:
            <path param name 1>: Path
            <path param name 2>: Path
            ...
        class run:
            <run param name 1>: <type 1>
            <run param name 2>: <type 2>
            ...

    config = Config()

(c) Alexandre René 2022-2025
https://github.com/alcrene/valconfig
"""
# %%

import sys
import os
import logging
from   collections import ChainMap
from   collections.abc import Mapping, Iterable
from   itertools import chain
import types
import typing
from   typing import Union, ClassVar, Optional, Literal, Any, Annotated, NamedTuple
from   pathlib import Path
from   warnings import warn
import tomllib

from pydantic import (BaseModel, Field, ValidationInfo, 
                      model_validator, field_validator)
from pydantic.main import PydanticUndefined

logger = logging.getLogger(__name__)

__all__ = ["ConfigPath", "ValConfig"]

# Module constants
_config_instances = {}

class FalsySentinel:
    def __init__(self, name=None):
        if name: self.__name__ = name
    def __str__(self): return self.__name__
    def __repr__(self): return self.__name__
    def __bool__(self): return False

class MissingDefaultError(ValueError):
    pass

IMPLICIT = FalsySentinel("IMPLICIT_DEFAULT")  # Used to indicate a default value which is programmatically defined (e.g. instantiations of nested ValConfigs)
KWARGS = FalsySentinel("KWARGS")   # Used to indicate the kwarg parameters in the sourced chain map

# %%

class SourcedChainMap(ChainMap):
    """
    The idea of a SourcedChainMap is to function as a dictionary, for which it
    is also possible to query where each value came from.
    The target use case is to combine dictionaries of configuration values,
    where some have higher precedence; for example “defaults” and “locals” dictionary.
    Each dictionary is associated a “source”, which can be any Python object;
    typical source types might be a string or a file path.

    CAUTION: Although the `maps` and `sources` attribute are mutable
          (as `maps` is in the base ChainMap), they must be kept in synced:
          any addition/removal to one must be applied to the other.
          So mutating the internal structure is not as safe as with ChainMap.
    TODO: Currently, modifications happen on the leftmost dict, so those data
          may become disassociated from their source.
          It would be better, if the leftmost dict is sourced, to create a new
          leftmost dict with source `None` before doing modifications.
    """
    def __init__(self, *maps, sources=()):
        if len(maps) != len(sources):
            raise ValueError()
        if maps:
            self.maps = list(maps)
            self.sources = list(sources)
        else:
            self.maps = [{}]
            self.sources = [None]
    def get_with_source(self, key, default=None) -> tuple[Any, Any]:
        """Retrieve both the value at `key` and its associated source.
        If no value is found, return `default` with a source of `None`.
        """
        for mapping, source in zip(self.maps, self.sources):
            try:
                return mapping[key], source
            except KeyError:
                pass
        return default, None   # Default value has source 'None' by convention
    def reversed_get(self, key, default=None) -> Any:
        """Retrieve the value with the lowest precedence.
        """
        for mapping in reversed(self.maps):
            try:
                return mapping[key]
            except KeyError:
                pass
        return default

    @classmethod
    def fromkeys(cls, iterable, *args):
        raise NotImplementError("`fromkeys` would erase the source information. If this is what you want, explicitely cast to `ChainMap` instead.")
    def new_child(self, m, source=None):
        """Pass `source=None` to add an unsourced mapping."""
        return self.__class__(m, *self.maps, sources=(source, *self.sources))
    def copy(self):
        'New ChainMap or subclass with a new copy of maps[0] and refs to maps[1:]'
        new_cm = super().copy()
        new_cm.sources = self.sources
        return new_cm
    @property
    def parents(self):
        'New ChainMap from maps[1:].'
        return self.__class__(*self.maps[1:], sources=self.sources[1:])
    def __ror__(self, other):
        raise NotImplementError("TODO")


# %%

class ConfigPath(Path):
    """
    The purpose of `ConfigPath` is to allow resolving paths relative to different anchors.
    
    - Absolute paths are never be modified.
    - Relative paths loaded from a **config file** can have three different anchors:
      + A path with no prefix, like `relative/to/file`, is relative to the **config file**.
      + A path with a dot prefix, like `./relative/to/cwd`, is relative to the **current directory**.
      + A path with the special marker `<PROJECTROOT>/root_file` is relative to the **project root**.
        The shorthand `$/root_file` can also be used for a path relative to the project root.
        The orthographies `<projectroot>` and `<ProjectRoot>` are also recognized
    - Relative paths set directly on the Config object are not associated to a config file;
      these are always relative to the **current directory**.

    Note that the project root is not automatically expanded: it works exactly like the home directory markers.
    To fully expand a path, use ``path.expandprojectroot()``.
    (If `.projectroot` contains a home directory marker "~", it is also expanded.)

    From the point of view of `ConfigPath`, a “project root” is just a Path which can
    be set during path creation or afterwards by assigning to the ``projectroot`` attribute.
    It is typically determined by moving up the directory tree,
    starting from the current working directory, until one of a set of
    predetermined files (like `.git` or `pyproject.toml`) is identified.
    See `ValConfig.load_config_files` for more details.
    
    """
    __slots__ = ("projectroot",)
    __projectroot_markers__ = {"$", "<PROJECTROOT>", "<projectroot>", "<ProjectRoot>"}

    def __init__(self, *pathsegments, anchor_dir=None, projectroot=None):
        self.projectroot = projectroot
        path = Path(*pathsegments)
        # Prepend the anchor_dir, but only if the path is not absolute
        # (NB: We don’t use `is_absolute()` here because we want "~/path" and "<PROJECTROOT>/path" to be considered as absolute)
        # Starting with a user '~' or projectroot marker counts as absolute
        # (the logic here is the same as in expandprojectroot)
        if (not (path.drive or path.root)                   # Probably not absolute
            and anchor_dir                                  # `anchor_dir` is not None
            and path._tail and (path._tail[0][:1] != "~"    # Not rel. to home dir
                                and path._tail[0] != "."    # Not rel. to CWD
                                and path._tail[0] not in self.__projectroot_markers__)):  # Not rel. to project root => Definitely not absolute
            drv, root, tail = self._parse_path(anchor_dir)
            pathsegments = (drv, root, *tail, *pathsegments)
        super().__init__(*pathsegments)

    def expandprojectroot(self, projectroot=None, projectrootmarkers=None):
        """ Return a new path with the project root marker (defined by __projectroot_marker__)
        replaced by the value of ``os.path.expanduser(self.projectroot)``.
        """
        projectroot = projectroot or self.projectroot
        projectrootmarkers = prm if (prm:=projectrootmarkers is not None) else self.__projectroot_markers__
        # (Implementation is exactly analogous to expanduser()
        if (not (self.drive or self.root) and
            self._tail and self._tail[0] in projectrootmarkers):
            if projectroot is None:
                raise RuntimeError("Must set `projectroot` before attempting to expand project root markers.")
            drv, root, tail = self._parse_path(os.path.expanduser(self.projectroot))
            return self._from_parsed_parts(drv, root, tail + self._tail[1:])
        return self

# %%


def parse_configpaths(cls, val: None|str|Path|ConfigPath, info: ValidationInfo) -> ConfigPath:
    """
    This validator is added to the ValConfig for every field of type `Path`.
    """
    # Normalization
    if val is None or isinstance(val, ConfigPath):
        return val
    if isinstance(val, Path):
        val = str(val)
    assert isinstance(val, str), f"Not a string (received {val} ({type(val)}) while validating {info.field_name})"
    if info.context:
        assert isinstance(info.context.sourced_data, SourcedChainMap), "Context is not a SourceChainMap — This is likely a bug in ValConfig"
        # Retrieve the source from the validation info
        data_val, source = info.context.sourced_data.get_with_source(info.field_name)
        if data_val != val:
            logger.debug(f"Path for field {info.field_name} was changed: was {data_val}, is now {val}. Data source is set to `None`.")
            source = None 
        # Infer the anchor directory from the source value
        if isinstance(source, Path):
            # The source will point to the actual config file, while the anchor should be the directory containing that file
            anchor_dir = source.parent
        elif source is KWARGS:
            anchor_dir = None
        elif not isinstance(source, (str, Path, type(None))):
            raise ValueError(f"Value for config key '{info.field_name}' has a source of unexpected type ({type(source)}). "
                             "This is likely an internal error.\n"
                             f"(Value received was {source})")
        else:
            anchor_dir = source
        projectroot = info.context.projectroot
    else:
        # If context is empty, we are probably validating a field assignment
        # There is no particular anchor directory,
        # but the projectroot class attribute should already be set
        anchor_dir = None
        projectroot = cls.__valconfig_projectroot__
    # Create the ConfigPath
    return ConfigPath(val, anchor_dir=anchor_dir, projectroot=projectroot)

# %%


def _flatten_annotations(ann):
    """
    Flatten annotations, including compound types like Optional[] and Union[].
    The effect is very similar to what `yield from Union[ann].__args__`
    would do, except that this doesn’t break if `ann` contains Typing objects
    like Optional.

    NB: Certain types, like 'str' or GenericaAlias, need to be special cased
        to avoid iterating into them. 
        The list of special cases may need to be occasionally updated, but
        should be manageable.
    """
    # In addition to types, catch Iterable objects we don’t actually want to iterate into
    if isinstance(ann, (type, str, types.GenericAlias, typing._GenericAlias)):
        yield ann
    elif isinstance(ann, Iterable):
        for a in ann:
            yield from _flatten_annotations(a)
    elif hasattr(ann, "__args__"):
        for a in ann.__args__:
            yield from _flatten_annotations(a)
    # If `ann` matches none of the above cases, then we don’t know what to do
    # with it and it would probably break something downstream, so we discard it.

class ValConfigContext(NamedTuple):
    sourced_data: SourcedChainMap
    projectroot: Path

class ValConfigMetaclass(type(BaseModel)):
    def __new__(meta, clsname, bases, namespace):
        """
        Transforms a Config class so that

            class Config(ValConfig):
                path1: Path
                path2: Path
                a: int
                b: float

                class figures:
                    size: tuple[float,float]


        becomes approximately

            class Config(ValConfig):
                path1: ConfigPath
                path2: ConfigPath
                a: int
                b: float

                class figuresType(ValConfig):
                    size: tuple[float,float]
                figures: figuresType

                @field_validator("path1", "path2", mode="before")
                @classmethod
                def parse_configpaths(...):
                    ...

        """
        annotations = namespace.get("__annotations__", {})
        annotation_types = {nm: set(_flatten_annotations(ann)) for nm, ann in annotations.items()}
        config_paths_to_validate = []
        # Iterate through annotations, looking for annotations `Path` and `Optional[Path]`
        for name, T in annotations.items():
            if T in {Path, "Path"}:
                annotations[name] = ConfigPath
                config_paths_to_validate.append(name)
            elif T in {Optional[Path], Optional["Path"]}:
                annotations[name] = ConfigPath | None
                config_paths_to_validate.append(name)
        # Add the required validator for those paths
        validator_name = "parse_configpaths"
        if validator_name in namespace:
            warn(f"Config class `{clsname}` already defines a `{validator_name}`, "
                 "which the name normally reserved for validators which convert Path values to ConfigPath. "
                 f"These validators, which were meant for values {config_paths_to_validate}, will not be added. "
                 f"If this was not intentional, please rename `{validator_name}`.")
        elif config_paths_to_validate:
            namespace[validator_name] = field_validator(*config_paths_to_validate, mode="before")(
                                            classmethod(parse_configpaths))

        # del config_paths_to_validate, validator_name, annotations
            # Pydantic assigns these __pydantic_parent_namespace__, which I’m pretty sure is unnecessary
            # Then again, it doesn’t seem to do any harm, so I will just let it be.
            # (It also adds 'name', 'T', 'meta', 'clsname', 'bases', 'namespace', which I would not know how to delete.)

        # Convert any bare subclasses to ValConfig subclasses
        # and create a corresponding attribute
        all_annotation_types = set(chain.from_iterable(annotation_types.values()))
        attribute_types = set(type(v) for v in namespace.values())
        nested_classes = {nm: val for nm, val in namespace.items()
                          if isinstance(val, type) and nm not in {"Config", "__config__"}}
        namespace_without_classes = {nm: val for nm, val in namespace.items()
                                     if nm not in nested_classes}
        new_nested_classes = {}
        for nm, T in nested_classes.items():
            # If a declared type was used, don't touch it or its name, and don't create an associated attribute
            if T in all_annotation_types | attribute_types:
                new_nested_classes[nm] = T
                continue
            # Otherwise, append `Type` to the name, to free the name itself for an annotation
            # NB: This only renames the nested attribute, not the type itself
            new_nm = nm + "Type"
            if new_nm in annotations.keys() | namespace_without_classes.keys():
                new_nm = nm  # Conflict -> no rename
            # If it isn't already a subclass of BaseModel, make it one
            if T.__bases__ == (object,):
                copied_attrs = {nm: attr for nm, attr in T.__dict__.items()
                                if nm not in {'__dict__', '__weakref__', '__qualname__', '__name__'}}
                newT = ValConfigMetaclass(nm, (ValConfig,), copied_attrs)
            else:
                if not issubclass(T, ValConfig):
                    logger.warning(f"For the nested Config class '{T.__qualname__}' "
                                   "to be automatically converted to a subclass of `BaseModel`, "
                                   "it must not inherit from any other class.")
                newT = T
            new_nested_classes[new_nm] = newT
            # Add a matching annotation
            if new_nm != nm:  # Ensure we aren't overwriting the type
                annotations[nm] = newT

        # Now we can let Pydantic parse the updated class
        return super().__new__(meta, clsname, bases,
                               {**namespace_without_classes,
                                **new_nested_classes,
                                '__annotations__': annotations,
                                '__valconfig_initialized__': False})


class ValConfig(BaseModel, metaclass=ValConfigMetaclass):
    """
    Augments a Pydantic BaseModel with the ability to
    - automatically load values from possibly multiple on-disk files;
    - automatically create fields from nested types, to reduce boilerplate.


    Typical package structure looks something like assumed:

        PROJECTROOT
        ├── .git
        ├── pyproject.py
        └── MyProject
            ├── config
            │    ├── __init__.py
            │    ├── defaults.toml
            │    └── [other config files]
            ├── local.toml
            └── [code files]

    `ValConfig` should be imported and instantiated from within
    ``MyProject.config.__init__.py``::

       from pathlib import Path
       from mackelab_toolbox.config import ValConfig

       class Config(ValConfig):
           arg1: <type>
           arg2: <type>
           ...

    The PROJECTROOT will be automatically recognized based on the detection
    of certain files; these include .git, pyproject.toml, poetry.lock and .smt
    The list of files can be changed by defining `__projectroot_filenames__`

    The `defaults.toml`, if present, must be located in the same directory
    as the module which *defines* the Config class. So in the example above,
    this means that it must be in the same directory as `__init__.py`.
    Note that this does *not* need to be under PROJECTROOT; for example,
    if you have installed your project with `pip`, the code will be in a
    separate site-packages directory. Just make sure that your package
    installation includes data files (see https://setuptools.pypa.io/en/latest/userguide/datafiles.html)
    and everything will continue to work.
    (If you want to change the path to the defaults, define `__default_config_path__` in your subclass.
    This is a path relative to the directory containing the module where Config is defined. )

    The `local.toml` files allow to override values in defaults.
    These should typically be **excluded** from version control, to allow other
    users to define their own overrides.
    `local.toml` files are identified by starting from the **current working directory**,
    and travelling up the hierarchy until we identify the PROJECTROOT.
    It is possible to have multiple local files; those closer to the working
    directory (i.e. with longer paths) are given higher precedence.
    (To change the name ValConfig will search for local configuration files,
    modify `__local_config_filename__`.)

    .. rubric:: Customization
       The naming conventions used by `ValConfig` are defined in class attributes,
       such as `__local_config_filename__` and `__sentinel_substitutions__`.
       These can all be changed, although only `__sentinel_substitutions__` has a clear use case.
       Change these values by overriding them in your own ValConfig subclass.
       (Don’t modify the value in the base class, as then any other package in your project which uses ValConfig may break.)
       So if you want to rename local config files to "userconf.toml" and add a
       substitution for "<SITEURL>", you could do the following::

           class Config(ValConfig):
             __default_config_path__: ClassVar = "userconf.toml"
             __sentinel_substitutions__: ClassVar = ValConfig | {"<SITEURL>": "https://ourcompany.com"}

       Note that you can also use Pydantic validators in your models to perform
       more complex value conversions.
    

    .. rubric:: Special support for path fields:
       All fields of type `Path` are converted to our custom type `ConfigPath`.
       This is a subclass of `Path` which adds support for PROJECTROOT:
       ConfigPaths may start with a project root marker, for example::
    
           <PROJECTROOT>/path/relative/to/projectroot
           $/another/path/relative/to/projectroot

       NB: For this to work, annotations must be either be `Path`, `Optional[Path]`
           or `Path | None`. Any other annotation (e.g. `Path | str`) will leave
           the Path type unchanged

    (The recognized markers are defined by ConfigPath.__projectroot_markers__.)
    To expand a ConfigPath, use `.expandprojectroot()`, in exact analogy to `.expanduser()`.

    There are some differences and magic behaviours compared to a plain
    BaseModel, which help to reduce boilerplate when defining configuration options:
    - Defaults are validated (`validate_all = True`).
    - Assignments are validated (`validate_assignments = True`)
    - Types which are not recognized by Pydantic are allowed as type hints; validators then just
      check that the passed value is of the correct type. (`arbitrary_types_allowed = True`)
      (NB: Using custom types will almost certainly require defining a validator for those fields,
       in order to parse the values loaded from config files.)
    - An option can explicitly request the default value with the special string "<DEFAULT>"
      This will be replaced by the value with the **lowest** precedence.
      Lowest precedence of all are the default defined in the class definition
      itself. Then values from `defaults.toml`, and finally values in `local.toml` in reverse precedence order.
      (The default marker can be changed by defining `__default_markers__`.)
    - Other sentinel can be defined by defining the dictionary `__sentinel_substitutions__`.
      By default this replaces "<None>" by a Python ``None`` value.

    - Nested plain classes are automatically converted to inherit ValConfig,
      and a new attribute of that class type is created. Specifically, if we
      have the following:

          class Config(ValConfig):
              class paths:
                  projectdir: Path

      then this is automatically converted to

          class Config(ValConfig):
              class pathsType(ValConfig):
                  projectdir: Path

              path : pathsType
    """
    __valconfig_initialized__ : ClassVar[bool]     = False
    __valconfig_projectroot__ : ClassVar[Path|None]= None

    __default_config_path__   : ClassVar[str]      = "defaults.toml"
    __local_config_filename__ : ClassVar[str]      = "local.toml"
    __projectroot_filenames__ : ClassVar[set[str]] = frozenset({".git", ".hg", ".smt", "pyproject.toml", "setup.cfg", "setup.py", "poetry.lock"})  # If one of these files occurs in a directory, stop searching hierarchy
    __default_value_markers__ : ClassVar[set[str]] = frozenset({"<default>", "<DEFAULT>"})

    __sentinel_substitutions__   : ClassVar[dict[str,Any]] = {"<None>": None, "<NONE>": None}

    model_config = dict(validate_default=True,         # Allow use simpler forms in class defaults, like `data_path: Path="/path/to/data"`
                        validate_assignment=True,      # Allow use of simpler forms when updating config values.
                        arbitrary_types_allowed=True,  # Allow passing arbitrary types: Pydantic will only check that they are instances. In particular, this allows us to support Path (and its replacement by ConfigPath) without any magic decorators
                        ignored_types=(ValConfigMetaclass,))  # ValConfig classes are allowed to contained nested ValConfigs

    ## Singleton pattern ##
    def __new__(cls, *a, **kw):
        if cls not in _config_instances:
            _config_instances[cls] = super().__new__(cls)
        return _config_instances[cls]
    def __copy__(x):  # Singleton => no copies
        return x
    def __deepcopy__(x, memo=None):
        return x

    ## Interface ##
    def __dir__(self):
        return list(self.__fields__)

    @property
    def projectroot(self):
        return self.__valconfig_projectroot__

    ## Initialization ##   # FIXME: What to do with projects that read the local config? Give project name to config?

    def __init__(self, **kwargs):
        if self.__valconfig_initialized__:
            config_data = SourcedChainMap()
            projectroot = self.__class__.__valconfig_projectroot__
        else:
            config_data, projectroot = self.load_config_files()
            self.__class__.__valconfig_projectroot__ = projectroot
        data = config_data.new_child(kwargs, source=KWARGS)

        # Merge the nested dictionaries for nested ValConfigs into their own SourcedChainMap()
        if not self.__valconfig_initialized__:  # TODO: Merge with conditional above. Note that we don’t want to unnecessarily instantiate types, in case they require args (which might be in `data`)
            cfgs = {}
            for nm, info in self.model_fields.items():
                T = info.annotation
                if not info.is_required(): continue
                if not isinstance(T, type) or not issubclass(T, ValConfig): continue
                if nm not in data:
                    cfgs[nm] = T()  # Instantiate with default params, which may retrieve an already initialized instance thanks to singleton pattern
            if cfgs:
                data = data.new_child(cfgs, source=IMPLICIT)

        # Calling the validator manually allows us to load the config files before checking for missing arguments.
        # Passing the data as a context allows individual validators to check the original source to resolve relative paths
        self.__pydantic_validator__.validate_python(
            data,
            self_instance=self,
            context=ValConfigContext(sourced_data=data, projectroot=projectroot)
        )

    # This methods is called manually from __init__
    # We could _almost_ achieve this by making it the first model_validator, except that
    # does not allow the Config object to be instantiated with missing arguments,
    # even if they would be defined in the config files
    @classmethod
    def load_config_files(cls) -> SourcedChainMap:
        """
        Load default values from the configuration files, and extend `data`
        with them. (Taking care not to overwrite existing fields in `data`.)
        This assumes that `data` is a dictionary.
        """

        config_dicts = SourcedChainMap()  # Stores data from each config file
        # NB: ChainMap precedence goes left to right
        #     `new_child` adds dictionaries to the left (i.e. gives them higher precedence)

        # If package provides a defaults file, it will be colocated in the same directory under the name defined by __default_config_path__
        # NB: This MIGHT NOT be under the current directory, especially if the package was installed to a `site_packages` folder.
        #     Relative paths should be interpreted as relative to the directory containing the config file
        if cls.__default_config_path__:
            module = sys.modules.get(cls.__module__)
            configdir = (Path.cwd() if module.__name__ == "__main__"
                         else Path(module.__file__).parent)
            if (p := configdir / cls.__default_config_path__).exists():
                with open(p, 'rb') as f:
                    try:
                        config_dicts = config_dicts.new_child(tomllib.load(f), source=p)
                    except tomllib.TOMLDecodeError as e:
                        msg = f"Unable to parse file with config defaults '{p}'."
                        if not p.suffix == ".toml":
                            msg.append(" Are you certain this is a TOML file?")
                        raise tomllib.TOMLDecodeError(f"{msg}\nThe original error message was:\n{e}")

        # Locate any local configurations:
        # Starting from the current directory, search for config files named 'local.toml'
        # in the hierarchy.
        local_paths = []
        d = Path.cwd()
        projectroot = None
        try:
            homedir = Path.home()
        except RuntimeError:
            homedir = None
        while not projectroot:
            for p in d.iterdir():
                if p.name == cls.__local_config_filename__:
                    local_paths.append(p)
                    logger.info(f"Appended '{p}' to local config files")
                if p.name in cls.__projectroot_filenames__:
                    projectroot = d  # Will terminate while loop
                    logger.info(f"Project root is '{d}'")
            if len(d._tail) == 0 or d == homedir:   # Fallback if there is no .git in the hierarchy and we reach the root or home directory
                logger.info(f"No project root found. `projectroot` is '{projectroot}'")
                break                               # Break while loop but don’t set 'projectroot'
            d = d.parent

        # Now load all the config files, from lowest to highest precedence
        for local_path in reversed(local_paths):
            with open(local_path, 'rb') as f:
                config_dicts = config_dicts.new_child(tomllib.load(f), source=local_path)

        return config_dicts, projectroot

    @model_validator(mode="before")
    @classmethod
    def replace_default(cls, data: SourcedChainMap, info: ValidationInfo):
        for nm, val in data.items():
            if isinstance(val, str) and val in cls.__default_value_markers__:
                field = cls.model_fields[nm]
                if field is not PydanticUndefined:
                    data[nm] = field.default
                else:
                    data[nm] = info.context.sourced_data.reversed_get(nm)
                if data[nm] in cls.__default_value_markers__:
                    raise MissingDefaultError(f"Field {nm} requested to use the default value, but no default value is defined.")
        return data

    @model_validator(mode="before")
    @classmethod
    def replace_sentinels(cls, data: SourcedChainMap):
        """Replace sentinel values by their definition in __setinel_substitutions__
        """
        for nm, val in data.items():
            if isinstance(val, str) and val in cls.__sentinel_substitutions__:
                data[nm] = cls.__sentinel_substitutions__[val]
        return data


# %%
