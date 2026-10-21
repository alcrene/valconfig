# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Command line interface for inspecting ValConfig objects.

Usage (from anywhere within a project):

    valconfig show                      # Auto-discover the project's config
    valconfig show mypackage.config     # Use the ValConfig instance in this module
    valconfig show mypackage.config:cfg # Use a specific attribute

Requires the optional dependencies `click` and `rich` (``pip install valconfig[cli]``).
"""

import sys
import re
import importlib
import tomllib
from   pathlib import Path
from   typing import Any

try:
    import click
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    from rich.pretty import pretty_repr
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(
        f"The valconfig CLI requires additional dependencies ({e.name} is missing). "
        "Install them with `pip install valconfig[cli]`.") from e

import pydantic_core
from pydantic import BaseModel, AnyUrl

from .valconfig import ValConfig, ConfigPath, KWARGS, find_projectroot

__all__ = ["cli"]

# Pseudo-source for computed fields, which don't come from a config file
COMPUTED = "computed"

# %% Locating the config object

def _candidate_modules(projectroot: Path) -> list[str]:
    """Return module names which plausibly contain the project's config."""
    candidates = []
    # First choice: the project name declared in pyproject.toml
    pyproject = projectroot/"pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as f:
            try:
                name = tomllib.load(f).get("project", {}).get("name")
            except tomllib.TOMLDecodeError:
                name = None
        if name:
            pkg = re.sub(r"[-.]", "_", name)
            candidates.append(f"{pkg}.config")
    # Fallback: any top-level package (flat or src layout) with a `config` submodule
    for base in (projectroot, projectroot/"src"):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if ((d/"__init__.py").exists()
                  and ((d/"config"/"__init__.py").exists() or (d/"config.py").exists())):
                modname = f"{d.name}.config"
                if modname not in candidates:
                    candidates.append(modname)
    return candidates

def _config_from_module(modname: str, attr: str|None) -> ValConfig:
    module = importlib.import_module(modname)
    if attr:
        if not hasattr(module, attr):
            raise click.ClickException(f"Module '{modname}' has no attribute '{attr}'.")
        obj = getattr(module, attr)
        if isinstance(obj, type) and issubclass(obj, ValConfig):
            obj = obj()   # Singleton: retrieves the already initialized instance, if there is one
        if not isinstance(obj, ValConfig):
            raise click.ClickException(f"'{modname}:{attr}' is not a ValConfig instance (it is a {type(obj)}).")
        return obj
    obj = getattr(module, "config", None)
    if isinstance(obj, ValConfig):
        return obj
    instances = {nm: v for nm, v in vars(module).items() if isinstance(v, ValConfig)}
    if len(instances) == 1:
        return next(iter(instances.values()))
    elif instances:
        raise click.ClickException(
            f"Module '{modname}' contains multiple ValConfig instances ({', '.join(instances)}). "
            f"Specify one with '{modname}:<name>'.")
    raise click.ClickException(f"Module '{modname}' does not contain a ValConfig instance.")

def load_config(target: str|None) -> ValConfig:
    """
    Import and return the config object designated by `target`, which should
    have the form ``module.path`` or ``module.path:attribute``.
    If `target` is None, try to discover the config object of the project
    containing the current directory.
    """
    cwd = Path.cwd()
    # NB: We can't know yet whether the project's Config overrides `__projectroot_filenames__`
    projectroot, _ = find_projectroot(cwd)
    # Make the current project importable, even if it is not installed
    for p in (projectroot/"src", projectroot, cwd) if projectroot else (cwd,):
        if p.is_dir() and str(p) not in sys.path:
            sys.path.insert(0, str(p))

    if target:
        modname, _, attr = target.partition(":")
        try:
            return _config_from_module(modname, attr or None)
        except ModuleNotFoundError as e:
            if e.name and modname.startswith(e.name):
                raise click.ClickException(f"Could not import '{modname}'.") from e
            raise

    if projectroot is None:
        raise click.ClickException(
            "Could not find a project root above the current directory. "
            "Specify the config module explicitly, e.g. `valconfig show mypackage.config`.")
    candidates = _candidate_modules(projectroot)
    errors = []
    for modname in candidates:
        try:
            return _config_from_module(modname, None)
        except ModuleNotFoundError as e:
            if e.name and modname.startswith(e.name):
                errors.append(f"{modname}: not found")
                continue
            raise
        except click.ClickException as e:
            errors.append(e.message)
    msg = f"Could not find a config object for the project at '{projectroot}'."
    if errors:
        msg += "\nTried:\n" + "\n".join(f"  - {err}" for err in errors)
    msg += "\nSpecify the config module explicitly, e.g. `valconfig show mypackage.config`."
    raise click.ClickException(msg)

# %% Formatting

def _format_type(T) -> str:
    if T is None:
        return ""
    s = T.__name__ if isinstance(T, type) else str(T)
    s = s.replace("typing.", "")
    return re.sub(r"\b(?:\w+\.)+(\w+)", r"\1", s)  # Strip module qualifiers

def _format_value(val, max_width=100) -> Text:
    if isinstance(val, ConfigPath):
        s = str(val)
        try:
            expanded = val.expandprojectroot()
        except RuntimeError:
            expanded = val
        text = Text(s, style="green")
        if str(expanded) != s:
            text.append(f"  → {expanded}", style="dim")
        return text
    elif isinstance(val, Path):
        return Text(str(val), style="green")
    elif val is None:
        return Text("None", style="italic dim")
    elif isinstance(val, bool):
        return Text(str(val), style="bold magenta" if val else "magenta")
    elif isinstance(val, (int, float, complex)):
        return Text(str(val), style="cyan")
    elif isinstance(val, str):
        return Text(repr(val), style="yellow")
    elif isinstance(val, (AnyUrl, pydantic_core.Url, pydantic_core.MultiHostUrl)):
        return Text(str(val), style="green")
    else:
        return Text(pretty_repr(val, max_width=max_width, max_length=10, max_string=max_width))

def _format_source(source, projectroot: Path|None) -> Text:
    if source is None:
        return Text("class default", style="dim")
    elif source is COMPUTED:
        return Text(COMPUTED, style="dim italic")
    elif source is KWARGS:
        return Text("keyword argument", style="magenta")
    elif isinstance(source, Path):
        for base, prefix in ((projectroot, "$/"), (Path.cwd(), "./")):
            if base:
                try:
                    return Text(prefix + str(source.relative_to(base)), style="blue")
                except ValueError:
                    pass
        try:
            return Text("~/" + str(source.relative_to(Path.home())), style="blue")
        except (ValueError, RuntimeError):
            return Text(str(source), style="blue")
    else:
        return Text(str(source))

# %% Building the table

def _add_rows(table: Table, config: ValConfig, model: BaseModel, path: tuple[str, ...],
              show_sources: bool, show_types: bool):
    """Add rows for the fields of `model`, which is the section of `config` at `path`."""
    indent = "  " * len(path)
    cls = type(model)
    for name, field in cls.model_fields.items():
        val = getattr(model, name)
        if isinstance(val, BaseModel):
            # Nested config: section header, then recurse
            table.add_row(Text(indent + name, style="bold"))
            _add_rows(table, config, val, path + (name,), show_sources, show_types)
            continue
        row = [Text(indent + name)]
        if show_types: row.append(Text(_format_type(field.annotation), style="dim"))
        row.append(_format_value(val))
        if show_sources:
            row.append(_format_source(config.get_source(*path, name), config.projectroot))
        table.add_row(*row)
    for name, field in cls.model_computed_fields.items():
        row = [Text(indent + name, style="italic")]
        if show_types: row.append(Text(_format_type(field.return_type), style="dim"))
        row.append(_format_value(getattr(model, name)))
        if show_sources: row.append(_format_source(COMPUTED, config.projectroot))
        table.add_row(*row)

def render_config(config: ValConfig, console: Console,
                  show_sources: bool=True, show_types: bool=True):
    cls = type(config)
    projectroot = config.projectroot
    data = cls.__valconfig_sourced_data__

    console.print(Text.assemble(("Config: ", "bold"), (f"{cls.__module__}.{cls.__qualname__}", "bold cyan")))
    console.print(Text.assemble(("Project root: ", "bold"), str(projectroot) if projectroot else ("(none found)", "dim")))
    if show_sources and data is not None:
        files = [src for src in data.sources if isinstance(src, Path)]
        console.print(Text("Config files (highest precedence first):", style="bold"))
        if not files:
            console.print(Text("  (none)", style="dim"))
        for src in files:
            console.print(Text(f"  {src}", style="blue"))

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Option", no_wrap=True)
    if show_types: table.add_column("Type", no_wrap=True)
    table.add_column("Value", overflow="fold")
    if show_sources: table.add_column("Source", no_wrap=True)
    _add_rows(table, config, config, (), show_sources, show_types)
    console.print()
    console.print(table)

# %% CLI

@click.group()
def cli():
    """Inspect ValConfig configuration objects."""

@cli.command()
@click.argument("target", required=False)
@click.option("--sources/--no-sources", default=True, show_default=True,
              help="Show which file (or default) each value comes from.")
@click.option("--types/--no-types", default=True, show_default=True,
              help="Show the declared type of each option.")
def show(target, sources, types):
    """Display the current values of a project's config.

    TARGET is a module path, optionally followed by ':attribute', e.g.
    'mypackage.config' or 'mypackage.config:config'.
    If omitted, the config is discovered from the project containing the
    current directory, by looking for a '<package>.config' module.

    Values are loaded exactly as they would be when running code from the
    current directory, since local config files are searched for starting
    from there.

    Sources are those recorded when the config was initialized; they do not
    reflect values modified afterwards (e.g. by assignment).
    """
    config = load_config(target)
    render_config(config, Console(), show_sources=sources, show_types=types)

def main():
    cli()

if __name__ == "__main__":
    main()
