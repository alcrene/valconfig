# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import datetime
from importlib.metadata import version

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'Validating Config'
author = 'Alexandre René'

try:
    version = version("valconfig")
except Exception:
    # Most likely project was not installed with setuptools
    version = "unknown"
release = version
this_year = datetime.date.today().year
copyright = f"2022-{this_year}, Alexandre René"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = ["myst_parser", "sphinx_design"]

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']

# Intersphinx config
intersphinx_mapping = {
    'python': ("https://docs.python.org/3/", None),
    'pydantic': ("https://docs.pydantic.dev/", None),
    'scityping': ("https://scityping.readthedocs.io/en/stable/", None)
}
intersphinx_disabled_reftypes = ["*"]

myst_heading_anchors = 3
myst_enable_extensions = [
    "colon_fence",
    "deflist"
]

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_book_theme'
html_static_path = ['_static']
