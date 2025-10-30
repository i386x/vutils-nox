[![Coverage Status](https://coveralls.io/repos/github/i386x/vutils-nox/badge.svg?branch=main)](https://coveralls.io/github/i386x/vutils-nox?branch=main)

# vutils-nox: Shared Nox Configuration for Vutils

`vutils-nox` is an extension of [Nox](https://nox.thea.codes/en/stable/) that
contains a shared project and linters configurations and workflows, mostly
intended to be used by `vutils-*` packages.

## Installation

`vutils-nox` can be installed via `pip`:

```console
$ pip install vutils-nox
```

For other options, see the next section.

## Usage

To start using `vutils-nox` workflows, just add to your `noxfile.py`:

```python
from vutils.nox.nox import setup

setup()
```

Importing `vutils.nox.nox` will populate Nox sessions registry with the
predefined sessions, `setup()` ensures that Nox will run these sessions
correctly and efficiently.

With the Nox feature to [load dependencies from `pyproject.toml` or scripts](https://nox.thea.codes/en/stable/tutorial.html#loading-dependencies-from-pyproject-toml-or-scripts)
you do not even have `vutils-nox` installed. Just make sure your `noxfile.py`
contains

```python
# /// script
# dependencies = ["nox", "vutils-nox"]
# ///

from vutils.nox.nox import setup

setup()
```

and Nox will install `vutils-nox` for you to its own dedicated environment.
