#
# File:    ./src/vutils/nox/utils.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-03 23:07:35 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Helpers and utilities."""

import os.path
import pathlib


def data2str(data):
    """"""
    if isinstance(data, dict):
        yield "{"
        for key, value in data:
            if not isinstance(key, str):
                raise TypeError("Only text keys are allowed")
            yield f"{key}="
            yield from data2str(value)
            yield ","
        yield "}"
    elif isinstance(data, list):
        yield "["
        for item in data:
            yield from data2str(item)
            yield ","
        yield "]"
    elif isinstance(data, bool):
        yield "True" if data else "False"
    elif isinstance(data, int):
        yield f"{data}"
    elif isinstance(data, str):
        yield f'("{data}")'
    else:
        raise TypeError(f"Unexpected object: {data!r}")


def resolve_path(path):
    """"""
    return pathlib.Path(os.path.expandvars(os.path.expanduser(path))).resolve()


def relative_path(path):
    """"""
    return path.relative_to(pathlib.Path.cwd(), walk_up=True)


def is_installed(session, package):
    """"""
    script = (
        "from importlib.metadata import packages_distributions as pds;"
        f' print("{package}" in {{d for ds in pds().values() for d in ds}})'
    )
    output = session.run("python", "-c", script, silent=True, log=False)
    return output.strip().lower() == "true"
