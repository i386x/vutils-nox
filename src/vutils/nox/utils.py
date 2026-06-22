#
# File:    ./src/vutils/nox/utils.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-03 23:07:35 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Helpers and utilities."""

import contextlib
import filecmp
import functools
import json
import os
import os.path
import pathlib
import re
import shutil
import types
from collections.abc import (
    Iterable,
    Mapping,
    MutableMapping,
    MutableSequence,
    Sequence,
)
from typing import TYPE_CHECKING, Generator, Literal

from nox.logger import logger
from nox.sessions import Session
from nox.virtualenv import CondaEnv, VirtualEnv
from typing_extensions import TypeIs

if TYPE_CHECKING:
    from vutils.nox import StrPath

#: Keywords
KW_PYTHON: Literal["python"] = "python"

#: Boolean constants names
FALSE = "false"
TRUE = "true"
BOOLEANS = (FALSE, TRUE)

#: File names
DIST_DIR_NAME = "dist"

#: Environment variables
EV_PYTHONPATH = "PYTHONPATH"
CI_ENV_VARS = ("CI", "GITHUB_TOKEN")
DANGER_ENV_VARS = {EV_PYTHONPATH: None}

#: The separator between segments of a configuration item
DATAPATH_SEP = "::"

#: The regular expression for identifying import failures in the output of a
#: Python script
IMPORT_ERROR_RE = re.compile("Traceback|ModuleNotFoundError|ImportError")


def identical(lhs: object, rhs: object) -> bool:
    """
    Check whether two objects are identical.

    :param lhs: The left-hand side object
    :param rhs: The right-hand side object
    :return: :obj:`True` if both arguments are considered identical

    If both :xarg:`lhs` and :xarg:`rhs` are methods, check whether their
    ``__func__`` attributes are identical (since ``o.m is o.m`` is always
    :obj:`False` for methods). Otherwise, use the ``is`` operator to perform
    the check.
    """
    if isinstance(lhs, types.MethodType) and isinstance(rhs, types.MethodType):
        return identical(lhs.__func__, rhs.__func__)
    return lhs is rhs


def is_sequence(obj: object) -> TypeIs[Sequence[object]]:
    """
    Narrow the type of :xarg:`obj` to the sequence.

    :param obj: The object
    :return: :obj:`True` if :xarg:`obj` is a sequence
    """
    return isinstance(obj, Sequence)


def is_mapping(obj: object) -> TypeIs[Mapping[object, object]]:
    """
    Narrow the type of :xarg:`obj` to the mapping.

    :param obj: The object
    :return: :obj:`True` if :xarg:`obj` is a mapping
    """
    return isinstance(obj, Mapping)


def is_mutable_mapping(obj: object) -> TypeIs[MutableMapping[object, object]]:
    """
    Narrow the type of :xarg:`obj` to the mutable mapping.

    :param obj: The object
    :return: :obj:`True` if :xarg:`obj` is a mutable mapping
    """
    return isinstance(obj, MutableMapping)


def data2str(data: object) -> Generator[str, None, None]:
    """
    Convert structured data into string.

    :param data: The structured data
    :return: the generator object yielding the string representation of
        :xarg:`data`
    :raises TypeError: when :xarg:`data` contain items with a wrong type

    Can be used to obtain the checksum of the data.
    """
    if is_mapping(data):
        yield "{"

        for key in data:
            if not isinstance(key, str):
                raise TypeError("Only text keys are allowed")
            yield f"{key}="
            yield from data2str(data[key])
            yield ","
        yield "}"
    elif isinstance(data, str):
        yield f'("{data}")'
    elif is_sequence(data):
        yield "["

        for item in data:
            yield from data2str(item)
            yield ","
        yield "]"
    elif isinstance(data, bool):
        yield "True" if data else "False"
    elif isinstance(data, int):
        yield f"{data}"
    else:
        raise TypeError(f"Unexpected object: {data!r}")


def container_at_path(
    data: MutableMapping[object, object], path: str
) -> tuple[MutableMapping[object, object], str]:
    """
    Get a container at the path.

    :param data: The data from which a container is extracted
    :param path: The path to a container within data
    :return: the found container and the last part of the path as a key to this
        container
    :raises TypeError: when :xarg:`data` contain items with a wrong type

    Traverse :xarg:`data` alongside :xarg:`path`, return a container that is
    located at the element just before the last element of :xarg:`path`. The
    last element of the :xarg:`path` is considered as a key for further
    manipulation with the container later when needed and as such it is then
    returned together with the container to be processed by a user. If the
    container does not exist alongside :xarg:`path` it is created. If
    :xarg:`path` cannot be fully traversed, e.g. because some location is
    occupied by object with wrong data type, an exception is raised.
    """
    parts = path.split(DATAPATH_SEP)
    key = parts.pop(-1).strip()
    container = data
    visited: MutableSequence[str] = []

    for part in parts:
        part = part.strip()
        visited.append(part)
        if part not in container:
            container[part] = {}
        item = container[part]
        if not is_mutable_mapping(item):
            raise TypeError(f"{DATAPATH_SEP.join(visited)}: Not a mapping")
        container = item
    return (container, key)


class RemoveMarker:
    """
    Item remove marker.

    An item marked with this marker will be removed from a container.
    """


def mergeinsert(
    container: MutableMapping[object, object], item: object, key: object
) -> None:
    """
    Insert, remove, or merge an item into the container.

    :param container: The container
    :param item: The item
    :param key: The key under which the item is stored into or removed from the
        container

    If the item is :class:`.RemoveMarker`, the item that is stored under the
    key is removed from the container. If both the item and the item stored in
    the container under the key are mappings, the item is recursively merged
    into the item stored under the key in the container. Otherwise, the item is
    just stored under the key into the container.
    """
    if item is RemoveMarker:
        if key in container:
            del container[key]
    elif (
        key in container
        and is_mutable_mapping(container[key])
        and is_mapping(item)
    ):
        for ikey in item:
            mergeinsert(container[key], item[ikey], ikey)
    else:
        container[key] = item


def log_diff(
    recent: Mapping[object, object], old: Mapping[object, object]
) -> None:
    """
    Log the difference between the recent and old metadata.

    :param recent: The recent metadata
    :param old: The old metadata
    """
    for key in recent:
        if key not in old:
            logger.info("METADATA: `%s` added", key)
        elif recent[key] != old[key]:
            logger.info(
                "METADATA: `%s` changed from `%s` to `%s`",
                key,
                repr(old[key]),
                repr(recent[key]),
            )
    for key in old:
        if key not in recent:
            logger.info("METADATA: `%s` removed", key)


def resolve_path(path: "StrPath") -> os.PathLike[str]:
    """
    Resolve :xarg:`path`.

    :param path: The path to be resolved
    :return: the resolved path
    """
    return pathlib.Path(
        os.path.expandvars(pathlib.Path(path).expanduser())
    ).resolve()


def relative_path(path: os.PathLike[str]) -> os.PathLike[str]:
    """
    Make :xarg:`path` relative to the current working directory.

    :param path: The path
    :return: :xarg:`path` relative to the current working directory
    """
    return path.relative_to(pathlib.Path.cwd(), walk_up=True)


def __build_file_map(
    files: Iterable[os.PathLike[str]],
) -> Mapping[str, os.PathLike[str]]:
    """
    Build the file map from a file list.

    :param files: The file list
    :return: the file map
    :raises ValueError: when a file is already in a file map

    A file map is a mapping between the name of a file and its path.
    """
    file_map: MutableMapping[str, os.PathLike[str]] = {}

    for item in files:
        name = item.stem
        if name in file_map:
            raise ValueError(f"`{name}` is already in a file map")
        file_map[name] = item
    return file_map


def __compare_files(
    recent: Mapping[str, os.PathLike[str]], old: Mapping[str, os.PathLike[str]]
) -> bool:
    """
    Compare two sets of files.

    :param recent: The recent set of files (file map)
    :param old: The old set of files (file map)
    :return: :obj:`True` if the two sets are equal, including file content

    If the two sets are different, the first found difference is logged.
    """
    for key in recent:
        if key not in old:
            logger.info("METADATA: File `%s` added", recent[key])
            return False
        if not filecmp.cmp(recent[key], old[key], shallow=False):
            logger.info(
                "METADATA: File `%s` changed (recent: `%s`)",
                old[key],
                recent[key],
            )
            return False
    for key in old:
        if key not in recent:
            logger.info("METADATA: File `%s` removed", old[key])
            return False
    return True


def compare_files(
    recent: Iterable[os.PathLike[str]], old: Iterable[os.PathLike[str]]
) -> bool:
    """
    Compare two lists of files.

    :param recent: The recent list of files
    :param old: The old list of files
    :return: :obj:`True` if the two lists are equal

    Two file lists are considered equal when:

    * their sets of file names of their files are equal
    * two files with the same name have also the same content
    """
    return __compare_files(__build_file_map(recent), __build_file_map(old))


def get_metadata_from_pkg(session: Session, package: str) -> object:
    """
    Extract metadata from the installed package.

    :param session: The Nox session
    :param package: The name of the package
    :return: the metadata as a JSON object
    :raises ValueError: when the attempt to get metadata has failed

    Extract metadata from the package installed in the Python virtual
    environment.
    """
    script = (
        "import json; import sys;"
        " from importlib.metadata import distribution as d;"
        f' json.dump(d("{package}").metadata.json, sys.stdout)'
    )
    metadata = run_script(session, script)
    if not metadata.startswith("{"):
        raise ValueError(f"Failed to obtain metadata from `{package}`.")
    return json.loads(metadata)


def get_pkg_metadata_dir(session: Session, package: str) -> os.PathLike[str]:
    """
    Get the metadata directory of the installed package.

    :param session: The Nox session
    :param package: The name of the package
    :return: the path to the package's metadata directory
    """
    script = (
        "from importlib.metadata import distribution as d;"
        f' print(d("{package}")._path)'
    )
    return pathlib.Path(run_script(session, script))


@functools.cache
def inside_ci() -> bool:
    """
    Return :obj:`True` if we are running inside CI.

    :return: :obj:`True` when running inside CI
    """
    return any(x in os.environ for x in CI_ENV_VARS)


@functools.cache
def dist_dir() -> os.PathLike[str]:
    """
    Return the path to the ``./dist`` directory.

    :return: the path to the ``./dist`` directory
    """
    return pathlib.Path.cwd() / DIST_DIR_NAME


def rm_dist_dir() -> None:
    """Remove ``./dist`` directory."""
    path = dist_dir()
    if path.is_dir():
        shutil.rmtree(path)


@functools.cache
def docs_dir() -> os.PathLike[str]:
    """
    Return the path to the ``./docs`` directory.

    :return: the path to the ``./docs`` directory
    """
    return pathlib.Path.cwd() / "docs"


@functools.cache
def src_dir() -> os.PathLike[str]:
    """
    Return the path to the ``./src`` directory.

    :return: the path to the ``./src`` directory
    """
    return pathlib.Path.cwd() / "src"


@functools.cache
def tests_dir() -> os.PathLike[str]:
    """
    Return the path to the ``./tests`` directory.

    :return: the path to the ``./tests`` directory
    """
    return pathlib.Path.cwd() / "tests"


@functools.cache
def utests_dir() -> os.PathLike[str]:
    """
    Return the path to the ``./tests/unit`` directory.

    :return: the path to the ``./tests/unit`` directory
    """
    return tests_dir() / "unit"


@functools.cache
def integs_dir() -> os.PathLike[str]:
    """
    Return the path to the ``./tests/integration`` directory.

    :return: the path to the ``./tests/integration`` directory
    """
    return tests_dir() / "integration"


def project_dirs(relative: bool = False) -> Iterable[os.PathLike[str]]:
    """
    Get the list of existing project directories.

    :param relative: The flag indicating whether paths should be relative to
        the project's root directory
    :return: the list of existing project directories

    The project directories are meant to be directories containing the source
    code, documentation, and tests of the project. Namely, these are
    ``./docs``, ``./src``, ``./tests/unit``, and ``./tests/integration``
    directories.
    """
    return [
        (relative_path(d) if relative else d)
        for d in (docs_dir(), src_dir(), utests_dir(), integs_dir())
        if d.is_dir()
    ]


def remove_build_artifacts() -> None:
    """Remove artifacts produced by ``python -m build``."""
    path = src_dir()
    if not path.is_dir():
        return
    for egg_info in path.glob("*.egg-info"):
        if egg_info.is_dir():
            shutil.rmtree(egg_info)


def envvar_is_unset(session: Session, name: str) -> None:
    """
    Assert that the environment variable is not set.

    :param session: The Nox session
    :param name: The name of the environment variable
    :raises RuntimeError: when the environment variable is not unset
    """
    if name in session.env and session.env[name] is None:
        return
    if name in session.env or name in os.environ:
        raise RuntimeError(f"Environment variable {name} is not unset")


@contextlib.contextmanager
def setenv(
    session: Session, env: Mapping[str, str | None]
) -> Generator[None, None, None]:
    """
    Set the environment variables for this context.

    :param session: The Nox session
    :param env: The mapping with environment variables to be set
    :return: the generator object

    If an environment variable has :obj:`None` value, the environment variable
    is unset for this context.
    """
    backup = {key: session.env[key] for key in env if key in session.env}

    try:
        session.env.update(env)
        yield
    finally:
        for key in env:
            if key not in backup:
                del session.env[key]
            else:
                session.env[key] = backup[key]


def run_script(session: Session, script: str) -> str:
    """
    Run the script under the session.

    :param session: The Nox session
    :param script: The script
    :return: the script output
    """
    return session.run(KW_PYTHON, "-c", script, silent=True, log=False).strip()


def interpreter(session: Session) -> str:
    """
    Get the real Python interpreter binary name.

    :param session: The Nox session
    :return: the real Python interpreter binary name for the :xarg:`session`
    """
    script = (
        "import sys; import pathlib;"
        " print(pathlib.Path(sys.executable).resolve().name)"
    )
    return run_script(session, script)


def is_installed(session: Session, package: str) -> bool:
    """
    Check whether the package is installed.

    :param session: The Nox session
    :param package: The package
    :return: :obj:`True` if :xarg:`package` is installed
    """
    script = (
        "from importlib.metadata import packages_distributions as pds;"
        f' print("{package}" in {{d for ds in pds().values() for d in ds}})'
    )
    return run_script(session, script).lower() == TRUE


def is_installed_as_editable(session: Session, package: str) -> bool:
    """
    Check whether the package is installed as editable.

    :param session: The Nox session
    :param package: The package
    :return: :obj:`True` if :xarg:`package` is installed as editable
    :raises ValueError: when the status of :xarg:`package` cannot be decided

    Editable packages do not have their source files installed and/or they
    contain a special file starting with ``__editable__.``.
    """
    script = (
        "from importlib.metadata import distribution as d;"
        f' from operator import attrgetter as ag; z = d("{package}"); print('
        "z.files and ("
        '"__init__.py" not in map(ag("name"), z.files) or any('
        'x.name.startswith("__editable__.") for x in z.files)))'
    )
    output = run_script(session, script).lower()
    if output not in BOOLEANS:
        raise ValueError(f"Invalid output: `{output}`")
    return output == TRUE


def package_dir(session: Session, package: str) -> os.PathLike[str]:
    """
    Return the directory where the package's content is installed.

    :param session: The Nox session
    :param package: The importable package name
    :return: the directory where the package's content is installed (where the
        ``__init__.py`` is present)
    """
    script = f"import {package}; print({package}.__file__)"
    pkg_init_path = pathlib.Path(run_script(session, script))
    return pkg_init_path.parent.resolve()


def packages_dir(session: Session, package: str) -> os.PathLike[str]:
    """
    Return the path to ``site-packages`` where the package is installed.

    :param session: The Nox session
    :param package: The importable package name
    :return: the path to the ``site-packages`` directory where the package is
        installed
    :raises OSError: if the ``site-packages`` directory cannot be located
    """
    pkgdir = package_dir(session, package)
    detail = f"`{pkgdir}` contains no `site-packages` part"
    while pkgdir != pkgdir.parent:
        if pkgdir.name == "site-packages":
            return pkgdir
        pkgdir = pkgdir.parent
    raise OSError(detail)


def upgrade_pip(session: Session) -> None:
    """
    Upgrade ``pip`` to its latest version.

    :param session: The Nox session
    """
    if (
        isinstance(session.virtualenv, (CondaEnv, VirtualEnv))
        and session.venv_backend != "uv"
    ):
        session.install("-U", "pip", silent=False)
