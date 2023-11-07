# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
A base classe for project config objects

For a package called `MyPackage`, the following files should be defined:

    MyPackage/MyPackage/config/__init__.py
    MyPackage/MyPackage/config/defaults.cfg
    MyPackage/local-config.cfg

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

(c) Alexandre René 2022-2023
https://github.com/alcrene/valconfig
"""
import os
import sys
import logging
from pathlib import Path
from collections import defaultdict
from collections.abc import Iterable, Mapping, Callable
from typing import Optional, Union, ClassVar#, _UnionGenericAlias  >= 3.9
from configparser import ConfigParser, ExtendedInterpolation
from contextlib import contextmanager
try:
    from pydantic.v1 import BaseModel, validator
except ModuleNotFoundError:
    from pydantic import BaseModel, validator
# from pydantic.main import ModelMetaclass
import textwrap

logger = logging.getLogger(__name__)

__all__ = ["ValConfig", "ensure_dir_exists"]

def _prepend_rootdir(cls, val):
    """Prepend any relative path with the current root directory."""
    if isinstance(val, Path):
        val = cls.resolve_path(val)
    return val

@contextmanager
def temp_setattr(obj, attr, value):
    """
    Temporarily set `obj.attr` to `value` iff `obj` already defines `attr`.
    The value of `obj.attr` is reset when we exit the context.
    """
    if hasattr(obj, attr):
        old_attr = getattr(obj, attr)
        setattr(obj, attr, value)
        try:
            yield obj
        finally:
            setattr(obj, attr, old_attr)
    else:
        yield obj

@contextmanager
def temp_match_attr(obj, src, attr):
    """
    Temporarily set `obj.attr` to the value of `src.attr`, iff both `obj`
    and `src` define `attr`.
    The value of `obj.attr` is reset when we exit the context.
    """
    if hasattr(obj, attr) and hasattr(src, attr):
        with temp_setattr(obj, attr, getattr(src, attr)) as newobj:
            yield newobj
    else:
        yield obj

class ValConfigMeta(type(BaseModel)):
    """
    Some class magic with nested types:
    1. If a nested type is also used to declare a value or annotation, it is
       left untouched.
    2. If a nested type is declared but not used, do the following:
       1. Convert it to a subclass of `BaseModel` if it isn't already one.
          This allows concise definition of nested configuration blocks.
       2. Declare an annotation with this type and the same name.
          ('Type' is appended to the attribute declaring the original type,
          to prevent name conflicts.)
          Exception: If "<typename>Type" is already used in the class, and thus
          would cause conflicts, no annotation is added.
    """
    def __new__(metacls, cls, bases, namespace):
        # Use ValConfig annotations as default.
        # However, in order not to lose a default if the user *didn't* assign to that attribute,
        # we only use annotation defaults for values which are also in `namespace`.
        default_annotations = {} if cls  == "ValConfig" \
                                 else ValConfig.__annotations__
        annotations = {**{nm: ann for nm, ann in default_annotations.items()
                          if nm in namespace},
                       **namespace.get("__annotations__", {})}
        if annotations:
            # Unfortunately a simple `Union[annotations.values()].__args__` does not work here
            def deref_annotations(ann):
                if isinstance(ann, Iterable):
                    for a in ann:
                        yield deref_annotations(a)
                elif hasattr(ann, "__args__"):
                    for a in ann.__args__:
                        yield deref_annotations(a)
                else:
                    yield ann
            annotation_types = set(deref_annotations(T) for T in annotations.values())
        else:
            annotation_types = set()
        attribute_types = set(type(v) for v in namespace.values())
        nested_classes = {nm: val for nm, val in namespace.items()
                          if isinstance(val, type) and nm not in {"Config", "__config__"}}
        new_namespace = {nm: val for nm, val in namespace.items()
                         if nm not in nested_classes}
        new_nested_classes = {}
        for nm, T in nested_classes.items():
            # If a declared type was used, don't touch it or its name, and don't create an associated attribute
            if T in annotation_types | attribute_types:
                new_nested_classes[nm] = T
                continue
            # Otherwise, append `Type` to the name, to free the name itself for an annotation
            # NB: This only renames the nested attribute, not the type itself
            new_nm = nm + "Type"
            if new_nm in annotations.keys() | new_namespace.keys():
                new_nm = nm  # Conflict -> no rename
            # If it isn't already a subclass of BaseModel, make it one
            if T.__bases__ == (object,):
                copied_attrs = {nm: attr for nm, attr in T.__dict__.items()
                                if nm not in {'__dict__', '__weakref__', '__qualname__', '__name__'}}
                newT = ValConfigMeta(nm, (ValConfig,), copied_attrs)
                # newT = type(nm, (T,BaseModel), {})  
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

        # Create a `prepend_root` validator to any field which may be a Path
        # (This test isn’t sophisticated: a field with type like `Tuple[Path,Path]`
        # currently is not resolved, but would still be included.)
        # There is no harm in applying prepend_root to extra fields, so in
        # practice it is almost the same as using a "*" validator.
        # Reason for not using a "*" validator: that gets executed after any
        # custom validator, preventing validators from seeing the correct path.
        # NOTE: Although I don’t anticipate it being useful, a subclass could override
        # the prepend validator by defining its own `prepend_rootdir` method or attribute
        path_fields = [nm for nm, ann in annotations.items()
                       if "Path" in str(ann) and not "ClassVar" in str(ann)]
        if path_fields:
            validator_dict = {"prepend_rootdir": validator(*path_fields, allow_reuse=True)(_prepend_rootdir)}
        else:
            validator_dict = {}

        return super().__new__(metacls, cls, bases,
                               {**validator_dict,  # Place first so this validator has priority. Also, conceivably this allows a subclass to overwrite the validator
                                **new_namespace,
                                **new_nested_classes,
                                '__annotations__': annotations,
                                '__valconfig_initialized__': False})


# Singleton pattern
_config_instances = {}

class ValConfig(BaseModel, metaclass=ValConfigMeta):
    """
    Augments Python's ConfigParser with a dataclass interface and automatic validation.
    Pydantic is used for validation.

    The following package structure is assumed:

        code_directory
        ├── .gitignore
        ├── setup.py
        ├── project.cfg
        └── MyPkcg
            ├── [code files]
            └── config
                ├── __init__.py
                ├── defaults.cfg
                └── [other config files]

    `ValConfig` should be imported and instantiated from within
    ``MyPckg.config.__init__.py``::

       from pathlib import Path
       from mackelab_toolbox.config import ValConfig

       class Config(ValConfig):
           arg1: <type>
           arg2: <type>
           ...

       config = Config(Path(__file__).parent/".project-defaults.cfg")

    `project.cfg` should be excluded by `.gitignore`. This is where users can
    modify values for their local setup. If it does not exist, a template one
    is created from the contents of `.project-defaults.cfg`, along with
    instructions.

    There are some differences and magic behaviours compared to a plain
    BaseModel, which help to reduce boilerplate when defining configuration options:
    - Defaults are validated (`validate_all = True`).
    - Values of ``"<default>"`` are replaced by the hard coded default in the Config
      definition. (These defaults may be `None`.)
    - Nested plain classes are automatically converted to inherit ValConfig,
      and a new attribute of that class type is created. Specifically, if we
      have the following:

          class Config(ValConfig):
              class paths:
                  projectdir: Path

      then this is automatically converted to

          class Config(ValConfig):
              class pathsType:
                  projectdir: Path

              path : pathsType
    - The user configuration file is found by searching upwards from the current
      directory for a file matching the value of `Config.user_config_filename`
      (default: "project.cfg")
      + If multiple config files are found, **the most global one is used**.
        The idea of a global config files is to help provide consistency across
        a document. If a sub project is compiled as part of a larger one, we want
        to use the larger project's config, which may set things like font
        sizes and color schemes, for all figures/report pages.
      + If it is important that particular pages use particular options, the
        global config file is not the best place to set that. Rather, set
        those options in the file itself, or a sibling text file.
    # - If a user configuration file is not found, and the argument
    #   `ensure_user_config_exists` is `True`, then a new blank configuration file
    #   is created at the location we would have expected to find one: inside
    #   the nearest parent directory which is a version control repository.
    # - The `rootdir` value is the path of the directory containing the user config.
    # - All arguments of type `Path` are made absolute by prepending `rootdir`.
    #   Unless they already are absolute, or the class variable
    #   `make_paths_absolute` is set to `False`.
    #   !! NOT CURRENTLY TRUE !!: For reasons I don’t yet understandand, the
    #   mechanism to do this adds the correct validator, but it isn’t executed.
    #   For the moment, please import the `prepend_rootdir` function and apply it
    #   (wrapping with ``validator(field)(prepend_rootdir)`` to all relevant fields.


    Config class options
    --------------------

    __create_template_config: Set to `True` if you want a template config
        file to be created in a standard location when no user config file is
        found. Default is `False`. Typically, this is set to `False` for utility
        packages, and `True` for project packages.
        This option is ignored when `__local_config_filename__` is `None`.
    __interpolation__: Passed as argument to ConfigParser.
        Default is ExtendedInterpolation().
        (Note that, as with ConfigParser, an *instance* must be passed.)
    __empty_lines_in_values__: Passed as argument to ConfigParser.
        Default is True: this prevents multiline values with empty lines, but
        makes it much easier to indent without accidentally concatenating values.

    Inside config/__init__.py, one would have:

        config = Config(Path(__file__)/".defaults.cfg" 
    """

    ## Config class options ##
    # Class options use dunder names to avoid conflicts
    # __make_paths_absolute__  : ClassVar[bool]=True
    __default_config_path__   : ClassVar[Optional[Path]]=None
    __local_config_filename__ : ClassVar[Optional[str]]=None
    __create_template_config__: ClassVar[bool] = True  # If True, a template config file is created when no local file is found. Requires a default config set with __default_config_path__
    __interpolation__         : ClassVar = ExtendedInterpolation()
    __empty_lines_in_values__  = False
    __top_message_default__: ClassVar = """
        # This configuration file for '{package_name}' should be excluded from
        # git, so can be used to configure machine-specific variables.
        # This can be used for example to set output paths for figures, or to
        # set flags (e.g. using GPU or not).
        # Default values are listed below; uncomment and edit as needed.
        #
        # Note that this file was generated from a defaults file packaged with
        # '{package_name}': it may not include all available options, although
        # should include the most common ones. For a full list of options,
        # refer to {package_name}’s documentation, or inspect the
        # config module `{config_module_name}`.
        #
        # Adding a new config field is done by modifying the config module
        # `{config_module_name}`, located at {config_module_path}.
        
        """
    __value_substitutions__   : ClassVar = {"<None>": None}

    # Internal vars
    __valconfig_current_root__: ClassVar[Optional[Path]]=None  # Set temporarily when validating config files, in order to resolve relative paths
    __valconfig_deferred_init_kwargs__: ClassVar[list]=[]
    __valconfig_parsing_default__: ClassVar[bool] = False  # Set temporarily to True when parsing a defaults file (i.e. one packaged with the the code)


    def read_cfg_file(self, cfg_path: Path) -> dict:
        """
        Read the contents of the file `cfg_path` and convert them to a
        configuration dictionary.
        Hierarchical parameters should be represented by nested dictionaries.
        """
        cfp = ConfigParser(interpolation=self.__interpolation__,
                           empty_lines_in_values=self.__empty_lines_in_values__)
        cfp.read(cfg_path)

        # Convert cfp to a dict; this loses the 'defaults' functionality, but makes
        # it much easier to support validation and nested levels
        return {section: dict(values) for section, values in cfp.items()}


    ## Pydantic model configuration ##
    # `validation_assignment` must be True, other options can be changed.
    class Config:
        validate_all = True  # To allow specifying defaults with as little boilerplate as possible
                             # E.g. without this, we would need to write `mypath: Path=Path("the/path")`
        validate_assignment = True  # E.g. if a field converts str to Path, allow updating values with strings

    ## Singleton pattern ##
    def __new__(cls, *a, **kw):
        if cls not in _config_instances:
            _config_instances[cls] = super().__new__(cls)  # __init__ will add this to __instances
        return _config_instances[cls]
    def __copy__(x):  # Singleton => no copies
        return x
    def __deepcopy__(x, memo=None):
        return x

    ## Interface ##
    def __dir__(self):
        return list(self.__fields__)

    ## Initialization ##

    # TODO: Config file as argument instead of cwd ?
    def __init__(self,
                 # default_config_file: Union[None,str,Path]=None,
                 cwd: Union[None,str,Path]=None,
                 # ensure_user_config_exists: bool=False,
                 # rootdir: Union[str,Path],
                 # path_default_config=None, path_user_config=None,
                 # *,
                 # config_module_name: Optional[str]=None,
                 **kwargs
                 ):
        """
        Instantiate a `Config` instance, reading from both the default and
        user config files.
        If the user-editable config file does not exist yet, an empty one
        with instructions is created, at the root directory of the version-
        controlled repository. If there are multiple nested repositories, the
        outer one is used (logic: one might have a code repo separate from
        and imported by a project repo; this should go in the project repo).
        If no repository is found, no template config file is created.


        See also `ValConfig.ensure_user_config_exists`.
        
        Parameters
        ----------
        # default_config_file: Path to the config file used for defaults.
        #     SPECIAL CASE: If this value is None, then `ValConfig`
        #     behaves like `ValConfigBase`: no config file is parsed or
        #     created. This is intended for including as a component of a larger
        #     ValConfig.
        #     The assumption then is that all fields are passed by keywords.
        #     NOT TRUE: Currently we do the special case if kwargs is non-empty.
        cwd: "Current working directory". The search for a config file starts
            from this directory then walks through the parents. 
            The value of `None` indicates to use the current working directory;
            especially if running on a local machine, this is generally what
            you want, and is usually the most portable.
        *
        # config_module_name: The value of __name__ when called within the
        #     project’s configuration module.
        #     Used for autogenerated instructions in the template user config file.

        # **kwargs:
        #     Additional keyword arguments are passed to ConfigParser.

        Todo
        ----
        When multiple config files are present in the hierarchy, combine them.
        Relative paths in lower config files should still work.
        """
        if self.__valconfig_initialized__:
            # Already initialized; if there are new kwargs, validate them.
            self.validate_dict(kwargs)
            return

        # elif kwargs:
        #     # We have NOT yet initialized, but are passing keyword arguments:
        #     # this may happen because of __new__ returning an existing instance,
        #     # in which case this __init__ gets executed twice

        #     # We flush this list after we initialize
        #     valconfig_deferred_init_kwargs__.append(kwargs)

        #     import pdb; pdb.set_trace()
        #     self.__init__()
        #     self.validate_dict(kwargs)

        else:
            # Normal path: Initialize with the config files

            ## Read the default config file ##
            if self.__default_config_path__:
                # Get the directory which contains this file
                configdir = Path(sys.modules.get(self.__module__).__file__).parent
                # Make config_path relative to configdir, and convert to Path
                type(self).__default_config_path__ = configdir / self.__default_config_path__
                # This will use super().__init__ because __valconfig_initialized__ is still False
                with temp_setattr(type(self), "__valconfig_parsing_default__", True):
                    self.validate_cfg_file(self.__default_config_path__, **kwargs)
            else:
                # If there is no config file, then all defaults must be defined in Config definition
                # NB: validate_dict will detect that we are initializing and take care of calling __init__
                #     It’s important not to call __init__ directly, because validate_dict takes care of setting _current_root__ of nested types
                self.validate_dict(kwargs)
                # super().__init__(**kwargs)

            # Mark as initialized, so we don't take this branch twice
            # Also, this ensures that further config files use setattr() instead of __init__ to set fields
            type(self).__valconfig_initialized__ = True  # Singleton => Assign to class

            ## Read the local (user-specific) config file(s) ##
            # Any matching file in the hierarchy will be read; files deeper in the file hierarchy are read last, so have precedence
            if self.__local_config_filename__:
                cfg_fname = self.__local_config_filename__

                ## Search for a file with name matching `cfg_fname` in the current directory and its parents ##
                # If no project config is found, create one in the location documented above
                if cwd is None:
                    cwd = Path(os.getcwd())
                default_location_for_conf_filename = None  # Will be set the first time we find a .git folder
                cfg_paths = []
               
                rootdir = None
                for wd in [cwd, *cwd.parents]:
                    wdfiles = set(os.listdir(wd))
                    if cfg_fname in wdfiles:
                        rootdir = wd
                        cfg_paths.append(wd/cfg_fname)
                    if ({".git", ".hg", ".svn"} & wdfiles
                          and not default_location_for_conf_filename):
                        default_location_for_conf_filename = wd/cfg_fname

                if rootdir:
                    for cfg_path in reversed(cfg_paths):
                        self.validate_cfg_file(cfg_path)
                elif default_location_for_conf_filename is not None:
                    if self.__create_template_config__:
                        # We didn’t find a project config file, but we did find that
                        # we are inside a VC repo => place config file at root of repo
                        # `ensure_user_config_exists` creates a config file from the
                        # defaults file, listing all default values (behind comments),
                        # and adds basic instructions and the default option values
                        assert self.__default_config_path__, f"Cannot create a template file at {default_location_for_conf_filename} if `{type(self).__qualname__}.__default_config_path__` is not set."
                        self.add_user_config_if_missing(
                            self.__default_config_path__,
                            default_location_for_conf_filename)
                elif self.__create_template_config__:
                    logger.error(f"The provided current working directory ('{cwd}') "
                                 "is not part of a version controlled repository.")

            # ## Apply any deferred initialization kwargs ##
            # for kw in self.__valconfig_deferred_init_kwargs__:
            #     self.validate_dict(kw)
            # self.__valconfig_deferred_init_kwargs__.clear()

    # We use weird arg name below to avoid clashing with kwargs
    def validate_cfg_file(self, __valconfig_cfg_path__: Path, **kwargs):
        if not __valconfig_cfg_path__.exists():
            logger.error(f"Config file path does not exist: '{__valconfig_cfg_path__}'")
        cfdict = self.read_cfg_file(__valconfig_cfg_path__)

        # Validate as a normal dictionary
        # We set the current root so that relative paths are resolved based on
        # the location of their config file
        with temp_setattr(type(self), "__valconfig_current_root__", __valconfig_cfg_path__.parent.absolute()):
            self.validate_dict({**cfdict, **kwargs})  # Keyword args are given precedence over file arguments

        # type(self).__valconfig_current_root__ = cfg_path.parent.absolute()
        # self.validate_dict({**cfdict, **kwargs})  # Keyword args are given precedence over file arguments
        # type(self).__valconfig_current_root__ = None

    def validate_dict(self, cfdict):
        """
        Note: This function relies on `validate_assignment = True`

        QoL feature: "one-level-up" as a default value
            If there is no "pckg.colors" section, but there is a "colors" section,
            use "colors" for "pckg.colors", if pckg expects that section.

            This allows setting an option once, and all nested configs will
            share the same value.

        CONSEQUENCE: Settings at the top level will overwrite any settings with
           the same name in nested settings. I’m not sure yet if this is a good
           thing. In general it can be convenient, and it’s not hard to reset
           options in nested configs if necessary, but it is somewhat unexpected
           behaviour.

        """

        # There are two code paths into this function:
        # - When updating an already initialized config
        # - When validating a config file (validate_cfg_file)


        # Convert any dotted sections into dict hierarchies (and merge where appropriate)
        cfdict = _unflatten_dict(cfdict)

        # Use "one-level-up" as a default value
        # So if there is no "pckg.colors" section, but there is a "colors" section,
        # use "colors" for "pckg.colors", if pckg expects that section.
        for fieldnm, field in self.__fields__.items():
            # Having Union[ValConfig, other type(s)] could break the logic of the next test; since we have no use case, just detect, warn and exit
            # if isinstance(field.type_, _UnionGenericAlias):  ≥3.9
            if str(field.type_).startswith("typing.Union"):
                if any((isinstance(T, type) and issubclass(T, ValConfig))
                       for T in field.type_.__args__):
                    raise TypeError("Using a subclass of `ValConfig` inside a Union is not supported.")
            elif isinstance(field.type_, type) and issubclass(field.type_, ValConfig):
                if fieldnm not in cfdict:
                    cfdict[fieldnm] = {}
                else:
                    assert isinstance(cfdict[fieldnm], dict), f"Configuration field '{fieldnm}' should be a dictionary."  # Must be mutable
                subcfdict = cfdict[fieldnm]
                for subfieldnm, subfield in field.type_.__fields__.items():
                    if subfieldnm not in subcfdict and subfieldnm in cfdict:
                        # A field is missing, and a plausible default is available
                        # QUESTION: Should we make a (deep) copy, in case two validating configs make conflicting changes ?
                        subcfdict[subfieldnm] = cfdict[subfieldnm]

                # If we didn’t add anything, remove the blank dictionary
                if len(cfdict[fieldnm]) == 0:
                    del cfdict[fieldnm]
            elif ( fieldnm not in cfdict
                   and "DEFAULT" in cfdict
                   and isinstance(cfdict["DEFAULT"], Mapping)
                   and fieldnm in cfdict["DEFAULT"] ):
                # configparser convention: Use DEFAULT as a special section for default values
                cfdict[fieldnm] = cfdict["DEFAULT"][fieldnm]

        if self.__valconfig_initialized__:
            # Config has already been initialized => validate fields by setting them
            # NOTE: This relies on `validate_assignment = True`
            recursively_validate(self, cfdict)
        else:
            # TODO: Make & use a recursive version of temp_match_attr ?
            # We are initializing => Use __init__ to validate values
            # First update the __current_root__ of any nested ValConfig classes
            # Also set __initialized__ state back to False, so paths are resolved appropriately – see `resolve_path()`
            cur_roots = {name: (field.type_.__valconfig_current_root__,
                                field.type_.__valconfig_parsing_default__)
                         for name, field in self.__fields__.items()
                         if hasattr(field.type_, "__valconfig_current_root__")}
            for name in cur_roots:
                self.__fields__[name].type_.__valconfig_current_root__ = self.__valconfig_current_root__
                self.__fields__[name].type_.__valconfig_parsing_default__ = self.__valconfig_parsing_default__
            # Initialize values
            super().__init__(**cfdict)
            # Reset __current_root__ of nested classes
            for name, (old_root, old_parsing) in cur_roots.items():
                self.__fields__[name].type_.__valconfig_current_root__ = old_root
                self.__fields__[name].type_.__valconfig_parsing_default_ = old_parsing

    ## Validators ##

    # @validator("*")
    # def prepend_rootdir(cls, val):
    #     """Prepend any relative path with the current root directory."""
    #     if isinstance(val, Path):
    #         val = cls.resolve_path(val)
    #     return val

    @validator("*", pre=True)
    def reset_default(cls, val, field):
        """Allow to use defaults in the BaseModel definition.

        Config models can define defaults. To allow config files to specify
        that we want to use the hardcoded default, we interpret the string value
        ``"<default>"`` to mean to use the hardcoded default.
        """
        if val == "<default>":
            return field.default  # NB: If no default is set, this returns `None`
        else:
            return val

    @validator("*", pre=True)
    def value_substitutions(cls, val):
        try:
            return cls.__value_substitutions__[val]
        except (TypeError, KeyError):
            # TypeError: When `val` is not hashable
            # KeyError: When `val` is not in the dictionary
            return val

    # Validator utility
    @classmethod
    def resolve_path(cls, path: Path):
        """
        There are different contexts for a relative path specified in a
        config file, each with a different "obvious" resolution.
        This function considers the following situations:

        - Absolute paths are never modified.
        - Relative paths specified in a user-local config file should always be
          relative to that config file.
        - Relative *input* paths specified in a default config file should be
          relative to that config file. For example, a matplotlib style file
          might be packaged with the default config.
        - Relative *output* paths specified in a default config file should be
          relative to the *current directory*.
          For example, a path for storing produced figures. This should definitely
          not be relative to the default config file, which will likely be buried
          under some external package (very possibly under a `site-packages` 
          the user will never look into.)

        We use two heuristics to differentiate between cases, which should be
        reliable unless users intentionally break their assumptions:

        - If the `root/path` concatenation exists => Assume an input path.
          (Broken if a file or directory is added to this location manually.)
        - SPECIAL CASE: If `path` is simply "." and the current root is the
          default config => Always resolve relative to current directory,
          independent of whether it is an input or output path.
          (It would always exists, since the default config exists, but we
          expect that most of the time this would be meant as an output path.)
        """
        if isinstance(path, str):
            path = Path(path)
        else:
            assert isinstance(path, Path), "`resolve_path` expects a Path or a str."
        if not path.is_absolute():
            root = cls.__valconfig_current_root__
            if root:
                # NB: __valconfig_initialized__ is set to False exactly after we have
                #     set any default values in the class itself or a default config file
                # if not cls.__valconfig_initialized__:
                if cls.__valconfig_parsing_default__:
                    if str(path) == "." or not (root/path).exists():
                        root = os.getcwd()
                # path_in_default_config = (root == cls.__default_config_path__.parent)
                # if path_in_default_config and str(path) == ".": # Special case
                #     output_path = True
                # else:
                #     output_path = not (root/path).exists()
                # if path_in_default_config and output_path:
                #     root = os.getcwd()
                path = root/path
        return path

    ## User config template ##

    def add_user_config_if_missing(
        self,
        path_default_config: Union[str,Path],
        path_user_config: Union[str,Path],
        ):
        """
        If the user-editable config file does not exist, create it.

        Basic instructions are added as a comment to the top of the file.
        Their content is determined by the class variable `__top_message_default__`.
        The message variable can contain `format` fields matching two names:
        `package_name` and `config_module_name`. These are inferred from
        self.__module__ and self.__file__ respectively.

        Parameters
        ----------
        path_default_config: Path to the config file providing defaults.
            *Should* be version-controlled
        path_user_config: Path to the config file a user would modify.
            Should *not* be version-controlled
        """
        # Determine the dynamic fields for the info message added to the top
        # of the template config
        config_module_path = self.__file__
        config_module_name = self.__module__
        package_name, _    = self.__module__.split(".", 1)
            # If the ValConfig subclass is defined in ``mypkg.config.__init__.py``, this will return ``mypkg``.

        top_message = self.__top_message_default__
        # Remove any initial newlines from `top_message`
        for i, c in enumerate(top_message):
            if c != "\n":
                top_message = top_message[i:]
                break
        # Finish formatting top message
        top_message = textwrap.dedent(
            top_message.format(package_name=package_name,
                               config_module_name=config_module_name,
                               config_module_path=config_module_path))

        if not Path(path_user_config).exists():
            # The user config file does not yet exist – create it, filling with
            # commented-out values from the defaults
            with open(path_default_config, 'r') as fin:
                with open(path_user_config, 'x') as fout:
                    fout.write(textwrap.dedent(top_message))
                    stashed_lines = []  # Used to delay the printing of instructions until after comments
                    skip = True         # Used to skip copying the top message from the defaults file
                    for line in fin:
                        line = line.strip()
                        if skip:
                            if not line or line[0] == "#":
                                continue
                            else:
                                # We've found the first non-comment, non-whitespace line: stop skipping
                                skip = False
                        if not line:
                            fout.write(line+"\n")
                        elif line[0] == "[":
                            fout.write(line+"\n")
                            stashed_lines.append("# # Defaults:\n")
                        elif line[0] == "#":
                            fout.write("# "+line+"\n")
                        else:
                            for sline in stashed_lines:
                                fout.write(sline)
                            stashed_lines.clear()
                            fout.write("# "+line+"\n")
            logger.warning(f"A default project config file was created at {path_user_config}.")


## Convenience validators ##

def ensure_dir_exists(cls, dirpath):
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    return dirpath

## Utilities ##

def _unflatten_dict(d: Mapping) -> defaultdict:
    """Return a new dict where dotted keys become nested dictionaries.

    For example, ``{"a.b.c.d": 3}`` becomes
    ``{"a": {"b": {"c": {"d": 3}}}}``

    Keys are sorted before unflattening, so the order of items in `d` does not matter.
    Precedence is given to later, more specific keys. For example, the following
    dictionary::

       {"a": {"b1": 1, "b2": {"c": 3}},
        "a.b1": 10,
        "a.b2": {"c": 30},
        "a.b2.c": 300
        }

    would become::

       {"a": {"b1": 10, "b2": {"c": 300}}}

    Note how in this example we used::

        "a.b2": {"c": 30},

    All intermediate levels must be dictionaries, even if those values are
    ultimately not used. Otherwise an `AssertionError` is raised.

    """
    def new_obj(): return defaultdict(new_obj)
    obj = new_obj()

    # Logic inspired by https://github.com/mewwts/addict/issues/117#issuecomment-756247606
    for k in sorted(d.keys()):  # Use sorted keys for better reproducibility
        v = d[k]
        subks = k.split('.')
        last_k = subks.pop()
        _obj = obj
        for i, _k in enumerate(subks):
            try:
                _obj = _obj[_k]
            except KeyError:  # We can end up here if `obj[_k]` already exists but is not a default dict
                _obj[_k] = new_obj()
                _obj = _obj[_k]
            assert isinstance(obj, Mapping), \
                f"Configuration field '{'.'.join(subks[:i+1])}' should be a dictionary."
        # NB: Don't unflatten value dictionaries, otherwise we can't have configs
        #     like those in matplotlib: {'figure.size': 6}
        _obj[last_k] = v

    return obj

def recursively_validate(model: Union[BaseModel,ValConfig],
                         newvals: dict):
    for key, val in newvals.items():
        # `newvals` may specify invalid fields – e.g. a DEFAULT section,
        # or generic fields from a fallback field.
        # If they don’t match a config field, ignore them.
        if key not in model.__fields__:
            continue
        # If `val` is a Mapping, we want to assign it recursively
        # if the field is a nested Config.
        if isinstance(val, Mapping):
            cur_val = getattr(model, key, None)
            # Two ways to identify nested Config: has `validate_dict` method
            cur_val_validate_dict = getattr(cur_val, "validate_dict", None)
            if isinstance(cur_val_validate_dict, Callable):  # If `cur_val` is a addict.Dict, accessing a non-existing attribute returns an empty dict
                with temp_match_attr(type(cur_val), type(model), "__valconfig_current_root__"):
                    cur_val_validate_dict(val)
                # # Preliminary: Assign a value to __valconfig_current_root__, so paths can be resolved
                # if ( hasattr(type(cur_val), "__valconfig_current_root__")
                #      and hasattr(type(model), "__valconfig_current_root__") ):
                #     _old_root = cur_val.__valconfig_current_root__
                #     type(cur_val).__valconfig_current_root__ = type(model).__valconfig_current_root__
                # else:
                #     _old_root = "SENTINEL VALUE - NO __VALCONFIG_ROOT__"
                # # Actual validation
                # cur_val_validate_dict(val)
                # # Cleanup: Remove value to __valconfig_current_root__
                # if _old_root != "SENTINEL VALUE - NO __VALCONFIG_ROOT__":
                #     type(cur_val).__valconfig_current_root__ = _old_root
            # or is an instance of BaseModel.
            elif isinstance(cur_val, BaseModel):
                recursively_validate(cur_val, val)
            # Anything else is treated as normal data.
            # Note that we don’t recursively validate plain dicts: it’s not unlikely one would want to replace them with the new value
            else:
                setattr(model, key, val)
        else:
            setattr(model, key, val)  
