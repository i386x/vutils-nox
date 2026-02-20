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
import io
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
from nox.project import load_toml
from nox.sessions import Session
from nox.virtualenv import CondaEnv, VirtualEnv
from pyproject_metadata import StandardMetadata
from typing_extensions import TypeIs

if TYPE_CHECKING:
    from vutils.nox import StrPath

#: Keywords
KW_PYTHON: Literal["python"] = "python"

#: Boolean constants names
FALSE: str = "false"
TRUE: str = "true"
BOOLEANS: Iterable[str] = (FALSE, TRUE)

#: File names
DEFAULT_LICENSE_FILES: Iterable[str] = (
    "LICEN[CS]E*",
    "COPYING*",
    "NOTICE*",
    "AUTHORS*",
)
DIST_DIR_NAME: str = "dist"
PYPROJECT_TOML: str = "pyproject.toml"

#: Environment variables
EV_PYTHONPATH: str = "PYTHONPATH"
CI_ENV_VARS: Iterable[str] = ("CI", "GITHUB_TOKEN")
DANGER_ENV_VARS: Mapping[str, None] = {EV_PYTHONPATH: None}

#: The separator between segments of a configuration item
DATAPATH_SEP: str = "::"

#: The regular expression for identifying import failures in the output of a
#: Python script
IMPORT_ERROR_RE: re.Pattern = re.compile(
    "Traceback|ModuleNotFoundError|ImportError"
)

#: Selected metadata fields names
ATTR_KEY: str = "attr"
DYNAMIC_KEY: str = "dynamic"
FILE_KEY: str = "file"
FIND_KEY: str = "find"
LICENSE_FILES_KEY: str = "license-files"
PACKAGES_KEY: str = "packages"
PROJECT_KEY: str = "project"
SETUPTOOLS_KEY: str = "setuptools"
TOOL_KEY: str = "tool"
VERSION_KEY: str = "version"
WHERE_KEY: str = "where"


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


def is_iterable(obj: object) -> TypeIs[Iterable[object]]:
    """
    Narrow the type of :xarg:`obj` to the iterable.

    :param obj: The object
    :return: :obj:`True` if :xarg:`obj` is an iterable
    """
    return isinstance(obj, Iterable)


def is_iterable_of_strings(obj: object) -> TypeIs[Iterable[str]]:
    """
    Narrow the type of :xarg:`obj` to the iterable of strings.

    :param obj: The object
    :return: :obj:`True` if :xarg:`obj` is an iterable of strings
    """
    if is_iterable(obj):
        return all(isinstance(item, str) for item in obj)
    return False


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

        key: object
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

        item: object
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
    parts: MutableSequence[str] = path.split(DATAPATH_SEP)
    key: str = parts.pop(-1).strip()
    container: MutableMapping[object, object] = data
    visited: MutableSequence[str] = []

    part: str
    for part in parts:
        part = part.strip()
        visited.append(part)
        if part not in container:
            container[part] = {}
        item: object = container[part]
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
        ikey: object
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
    key: object
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
    pth: os.PathLike[str] = pathlib.Path(path)
    return pathlib.Path(os.path.expandvars(pth.expanduser())).resolve()


def relative_path(path: os.PathLike[str]) -> os.PathLike[str]:
    """
    Make :xarg:`path` relative to the current working directory.

    :param path: The path
    :return: :xarg:`path` relative to the current working directory
    """
    return path.relative_to(pathlib.Path.cwd(), walk_up=True)


def __build_file_map(
    files: Sequence[os.PathLike[str]],
) -> Mapping[str, os.PathLike[str]]:
    """
    Build the file map from a file list.

    :param files: The file list
    :return: the file map
    :raises ValueError: when a file is already in a file map

    A file map is a mapping between the name of a file and its path.
    """
    file_map: MutableMapping[str, os.PathLike[str]] = {}

    item: os.PathLike[str]
    for item in files:
        name: str = item.stem
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
    key: str
    for key in recent:
        if key not in old:
            logger.info("METADATA: File `%s` added", recent[key])
            return False
        elif not filecmp.cmp(recent[key], old[key], shallow=False):
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
    recent: Sequence[os.PathLike[str]], old: Sequence[os.PathLike[str]]
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


class HashableDict(dict):
    """
    Dictionary with hashing support.

    It was designed only for read-only dictionaries and as such it should be
    used only with them.
    """

    __slots__ = ()

    def __hash__(self) -> int:
        """
        Compute the hash of the dictionary.

        :return: the hash of the dictionary

        Currently it returns just this object :func:`id` since this object is
        supposed to be read-only.
        """
        return id(self)


@functools.cache
def load_pyproject(
    path: os.PathLike[str] | None = None,
) -> Mapping[str, object]:
    """
    Load ``pyproject.toml``.

    :param path: The path to the ``pyproject.toml``-like file or to the
        directory where the ``pyproject.toml`` file is present
    :return: the content of ``pyproject.toml``

    If :xarg:`path` is :obj:`None`, ``pyproject.toml`` is looked for in the
    current working directory. If :xarg:`path` is a directory,
    ``pyproject.toml`` is looked for in that directory. Otherwise, :xarg:`path`
    should point to a TOML file with a content satisfying the
    ``pyproject.toml`` content specification.
    """
    if path is None:
        path = pathlib.Path.cwd()
    if path.is_dir():
        path = path / PYPROJECT_TOML
    return HashableDict(load_toml(path))


def __error(errcls: type[Exception], pth: Sequence[str], detail: str) -> None:
    """
    Raise an error.

    :param errcls: The error class
    :param pth: The path to the origin of an error
    :param detail: The error detail
    :raises Exception: when invoked

    The helper for :func:`.__bad_type`.
    """
    loc: str = ".".join(pth)
    raise errcls(f"`{loc}`{detail}")


def __bad_type(pth: Sequence[str], expected: str) -> None:
    """
    Raise a type error.

    :param pth: The path to the origin of an error
    :param expected: The name of the expected type
    :raises TypeError: when invoked

    The helper for :func:`.get_version` and :func:`.get_dynamic`.
    """
    __error(TypeError, pth, f" must be {expected}")


@functools.cache
def get_version(pyproject: Mapping[str, object]) -> str | None:
    """
    Get the value of ``project.version``.

    :param pyproject: The ``pyproject.toml`` data
    :return: the version if it is present or :obj:`None`
    :raises TypeError: when the ``pyproject.toml`` data contain items with a
        wrong type
    """
    if PROJECT_KEY not in pyproject:
        return None
    pth: MutableSequence[str] = [PROJECT_KEY]
    project_sec: object = pyproject[PROJECT_KEY]
    if not is_mapping(project_sec):
        __bad_type(pth, "a mapping")
    if VERSION_KEY not in project_sec:
        return None
    pth.append(VERSION_KEY)
    version: object = project_sec[VERSION_KEY]
    if not isinstance(version, str) or len(version) == 0:
        __bad_type(pth, "a non-empty string")
    return version


@functools.cache
def get_license_files(pyproject: Mapping[str, object]) -> Iterable[str]:
    """
    Get the value of ``project.license-files``.

    :param pyproject: The ``pyproject.toml`` data
    :return: the list of license files globs
    :raises TypeError: when the ``pyproject.toml`` data contain items with a
        wrong type
    """
    if PROJECT_KEY not in pyproject:
        return DEFAULT_LICENSE_FILES
    pth: MutableSequence[str] = [PROJECT_KEY]
    project_sec: object = pyproject[PROJECT_KEY]
    if not is_mapping(project_sec):
        __bad_type(pth, "a mapping")
    if LICENSE_FILES_KEY not in project_sec:
        return DEFAULT_LICENSE_FILES
    pth.append(LICENSE_FILES_KEY)
    license_files: object = project_sec[LICENSE_FILES_KEY]
    if not is_iterable_of_strings(license_files):
        __bad_type(pth, "an iterable of strings")
    return license_files


@functools.cache
def get_dynamic(
    pyproject: Mapping[str, object], field: str
) -> tuple[str, str] | None:
    """
    Get the details about a dynamically specified field.

    :param pyproject: The ``pyproject.toml`` data
    :param field: The dynamically specified field name
    :return: the pair containing the directive name and the value associated
        with that directive or :obj:`None` if :xarg:`field` is not dynamic
    :raises TypeError: when the ``pyproject.toml`` data contain items with a
        wrong type
    :raises ValueError: when the ``pyproject.toml`` data contain items with a
        wrong value

    Get the value of :xarg:`field` from the ``tool.setuptools.dynamic``
    section. The first element of the returned pair is the name of a directive
    (either ``attr`` or ``file``) and the second element is the value
    associated with the directive (i.e. a fully qualified attribute name or a
    file name, respectively).
    """
    if TOOL_KEY not in pyproject:
        return None
    pth: MutableSequence[str] = [TOOL_KEY]
    tool_sec: object = pyproject[TOOL_KEY]
    if not is_mapping(tool_sec):
        __bad_type(pth, "a mapping")
    if SETUPTOOLS_KEY not in tool_sec:
        return None
    pth.append(SETUPTOOLS_KEY)
    setuptools_sec: object = tool_sec[SETUPTOOLS_KEY]
    if not is_mapping(setuptools_sec):
        __bad_type(pth, "a mapping")
    if DYNAMIC_KEY not in setuptools_sec:
        return None
    pth.append(DYNAMIC_KEY)
    dynamic_sec: object = setuptools_sec[DYNAMIC_KEY]
    if not is_mapping(dynamic_sec):
        __bad_type(pth, "a mapping")
    if field not in dynamic_sec:
        return None
    pth.append(field)
    record: object = dynamic_sec[field]
    if not is_mapping(record):
        __bad_type(pth, "a mapping")
    if len(record) != 1:
        __error(ValueError, pth, " size must be exactly 1")
    result: tuple[str, str] | None = None
    key: str
    for key in record:
        if key not in (ATTR_KEY, FILE_KEY):
            __error(ValueError, pth, f": invalid directive `{key}`")
        value: object = record[key]
        if not isinstance(value, str) or len(value) == 0:
            __bad_type(pth + [key], "a non-empty string")
        result = (key, value)
    return result


@functools.cache
def get_where(pyproject: Mapping[str, object]) -> Iterable[str] | None:
    """
    Get the value of ``tool.setuptools.packages.find.where``.

    :param pyproject: The ``pyproject.toml`` data
    :return: the list of directories, relative to the ``pyproject.toml``-like
        file directory, where to look for packages to be distributed or
        :obj:`None` if no such list is specified
    :raises TypeError: when the ``pyproject.toml`` data contain items with a
        wrong type
    """
    if TOOL_KEY not in pyproject:
        return None
    pth: MutableSequence[str] = [TOOL_KEY]
    tool_sec: object = pyproject[TOOL_KEY]
    if not is_mapping(tool_sec):
        __bad_type(pth, "a mapping")
    if SETUPTOOLS_KEY not in tool_sec:
        return None
    pth.append(SETUPTOOLS_KEY)
    setuptools_sec: object = tool_sec[SETUPTOOLS_KEY]
    if not is_mapping(setuptools_sec):
        __bad_type(pth, "a mapping")
    if PACKAGES_KEY not in setuptools_sec:
        return None
    pth.append(PACKAGES_KEY)
    packages_sec: object = setuptools_sec[PACKAGES_KEY]
    if not is_mapping(packages_sec):
        __bad_type(pth, "a mapping")
    if FIND_KEY not in packages_sec:
        return None
    pth.append(FIND_KEY)
    find_sec: object = packages_sec[FIND_KEY]
    if not is_mapping(find_sec):
        __bad_type(pth, "a mapping")
    if WHERE_KEY not in find_sec:
        return None
    pth.append(WHERE_KEY)
    where: object = find_sec[WHERE_KEY]
    if not is_iterable_of_strings(where):
        __bad_type(pth, "an iterable of strings")
    return where


def resolve_dynamic_version(
    session: Session, pyproject: Mapping[str, object]
) -> str:
    """
    Resolve dynamic version from ``pyproject.toml`` data.

    :param session: The Nox session
    :param pyproject: The ``pyproject.toml`` data
    :return: the resolved version
    :raises ValueError: when the version cannot be resolved due to invalid,
        insufficient, or missing data
    :raises OSError: when the file with the version cannot be opened for
        reading
    """
    dynver: tuple[str, str] | None = get_dynamic(pyproject, VERSION_KEY)
    if dynver is None:
        raise ValueError("Missing version")

    directive: str
    value: str
    directive, value = dynver
    if directive == ATTR_KEY:
        parts: Sequence[str] = value.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(f"`{value}` has no module name part")
        pypath: str | None = None
        where: Iterable[str] | None = get_where(pyproject)
        if where is not None:
            where = list(filter(None, where))
        if where:
            pypath = os.pathsep.join(where)
        with setenv(session, {EV_PYTHONPATH: pypath}):
            version: str = run_script(
                session, f"from {parts[0]} import {parts[1]} as x; print(x)"
            )
            if not version or IMPORT_ERROR_RE.search(version):
                raise ValueError(f"Invalid version: `{version}`")
            return version
    elif directive == FILE_KEY:
        path: os.PathLike[str] = resolve_path(value)
        if not path.is_file():
            raise OSError(f"`{path}` is not a file")
        fobj: io.TextIOWrapper
        with path.open() as fobj:
            version: str = fobj.read().strip()
            if not version:
                raise ValueError("Invalid version (empty string)")
            return version
    else:
        raise ValueError(f"Invalid directive: `{directive}`")


@functools.cache
def get_metadata(pyproject: Mapping[str, object]) -> StandardMetadata:
    """
    Extract metadata from the ``pyproject.toml`` content.

    :param pyproject: The content of the ``pyproject.toml``-like file
    :return: the metadata
    """
    return StandardMetadata.from_pyproject(pyproject)


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
    script: str = (
        "import json; import sys;"
        " from importlib.metadata import distribution as d;"
        f' json.dump(d("{package}").metadata.json, sys.stdout)'
    )
    metadata: str = run_script(session, script)
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
    script: str = (
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
def project_pythons() -> Sequence[str]:
    """
    Return the list of Python versions supported by the project.

    :return: the list of Python versions supported by the project
    """
    return [
        classifier.split()[-1]
        for classifier in get_metadata(load_pyproject()).classifiers
        if classifier.startswith("Programming Language :: Python :: 3.")
    ]


@functools.cache
def dist_dir() -> os.PathLike[str]:
    """
    Return the path to the ``./dist`` directory.

    :return: the path to the ``./dist`` directory
    """
    return pathlib.Path.cwd() / DIST_DIR_NAME


def rm_dist_dir() -> None:
    """Remove ``./dist`` directory."""
    path: os.PathLike[str] = dist_dir()
    if path.is_dir():
        shutil.rmtree(path)


@functools.cache
def src_dir() -> os.PathLike[str]:
    """
    Return the path to the ``./src`` directory.

    :return: the path to the ``./src`` directory
    """
    return pathlib.Path.cwd() / "src"


def remove_build_artifacts() -> None:
    """Remove artifacts produced by ``python -m build``."""
    path: os.PathLike[str] = src_dir()
    if not path.is_dir():
        return
    egg_info: os.PathLike[str]
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
    key: str
    backup: Mapping[str, str | None] = {
        key: session.env[key] for key in env if key in session.env
    }

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
    script: str = (
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
    script: str = (
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
    script: str = (
        "from importlib.metadata import distribution as d;"
        f' from operator import attrgetter as ag; z = d("{package}"); print('
        "z.files and ("
        '"__init__.py" not in map(ag("name"), z.files) or any('
        'x.name.startswith("__editable__.") for x in z.files)))'
    )
    output: str = run_script(session, script).lower()
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
    script: str = f"import {package}; print({package}.__file__)"
    pkg_init_path: os.PathLike[str] = pathlib.Path(run_script(session, script))
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
    pkgdir: os.PathLike[str] = package_dir(session, package)
    detail: str = f"`{pkgdir}` contains no `site-packages` part"
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
        session.install("-U", "pip")
