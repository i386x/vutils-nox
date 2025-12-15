#
# File:    ./src/vutils/nox/utils.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-03 23:07:35 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Helpers and utilities."""

from collections.abc import Sequence
import os
import os.path
import pathlib
from typing import TYPE_CHECKING

from nox.project import load_toml
from pydantic import BaseModel

from vutils.nox.command import Command

if TYPE_CHECKING:
    from collections.abc import (
        Iterable, Mapping, MutableMapping, MutableSequence
    )
    from typing import Generator, Literal, TypeGuard

    from nox.registry import get
    from nox.sessions import Session

    from vutils.nox import ActionType, StrPath

#: Constants and keywords
CI_ENV_VARS: Iterable[str] = ("CI", "GITHUB_TOKEN")
DATAPATH_SEP: str = "::"
KW_PYTHON: Literal["python"] = "python"
PYPROJECT_TOML: str = "pyproject.toml"


def is_dict(obj: object) -> TypeGuard[Mapping[object, object]]:
    """
    Narrow the type of :xarg:`obj` to the mapping.

    :param obj: The object
    :return: :obj:`True` if :xarg:`obj` has the :class:`dict` type
    """
    return isinstance(obj, dict)


def is_list(obj: object) -> TypeGuard[Iterable[object]]:
    """
    Narrow the type of :xarg:`obj` to the iterable.

    :param obj: The object
    :return: :obj:`True` if :xarg:`obj` has the :class:`list` type
    """
    return isinstance(obj, list)


def data2str(data: object) -> Generator[str]:
    """
    Convert structured data into string.

    :param data: The structured data
    :return: the generator object yielding the string representation of
        :xarg:`data`
    :raises TypeError: when :xarg:`data` are ill-formed

    Can be used to obtain the checksum of the data.
    """
    if is_dict(data):
        yield "{"

        key: object
        value: object
        for key, value in data:
            if not isinstance(key, str):
                raise TypeError("Only text keys are allowed")
            yield f"{key}="
            yield from data2str(value)
            yield ","
        yield "}"
    elif is_list(data):
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
    elif isinstance(data, str):
        yield f'("{data}")'
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
    :raises TypeError: if the path cannot be fully traversed

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
        if not is_dict(item):
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

    If the item is :class:`~.RemoveMarker`, the item that is stored under the
    key is removed from the container. If both the item and the item stored in
    the container under the key are mappings, the item is recursively merged
    into the item stored under the key in the container. Otherwise, the item is
    just stored under the key into the container.
    """
    if item is RemoveMarker:
        if key in container:
            del container[key]
    elif key in container and is_dict(container[key]) and is_dict(item):
        ikey: object
        for ikey in item:
            mergeinsert(container[key], item[ikey], ikey)
    else:
        container[key] = item


def resolve_path(path: StrPath) -> os.PathLike[str]:
    """
    Resolve :xarg:`path`.

    :param path: The path to be resolved
    :return: the resolved path
    """
    return pathlib.Path(os.path.expandvars(os.path.expanduser(path))).resolve()


def relative_path(path: os.PathLike[str]) -> os.PathLike[str]:
    """
    Make :xarg:`path` relative to the current working directory.

    :param path: The path
    :return: :xarg:`path` relative to the current working directory
    """
    return path.relative_to(pathlib.Path.cwd(), walk_up=True)


def is_action_callabel(action: ActionType | str) -> TypeGuard[ActionType]:
    """
    Check whether the action is callable.

    :param action: The action
    :return: :obj:`True` if the action is callable
    """
    return callable(action)


def normalize_actions(
    actions: Iterable[ActionType | str]
) -> Generator[ActionType]:
    """
    Normalize actions.

    :param actions: The list of actions or their names (can be intermixed)
    :return: the generator yielding actions that are only callables
    :raises KeyError: if an action is a name and that name is not present in
        the Nox registry
    :raises TypeError: if the action taken from the Nox registry is not an
        instance of :class:`~vutils.nox.command.Command`

    If an action is a callable it is yielded as it is. Otherwise, it is looked
    up in the Nox registry and the found callable is then yielded.
    """
    registry: Mapping[str, object] = get()

    action: ActionType | str
    for action in actions:
        if is_action_callable(action):
            yield action
        if action not in registry:
            raise KeyError(f"`{action}` is not in Nox registry")
        command: object = registry[action]
        if not isinstance(command, Command):
            raise TypeError(f"{command!r} is not a command")
        yield command


def normalize_description(desc: str) -> str:
    """
    Normalize description.

    :param desc: The description
    :return: the normalized description

    A description is normalized following these steps:

    #. select the first line
    #. make the first letter lowercase
    #. if the description ends with the dot is neither the part of ellipsis nor
       the entire description is the dot

       - remove the dot
    """
    desc = desc.strip().split("\n")[0].strip()
    if len(desc) > 0:
        desc = desc[0].lower() + desc[1:]
        if len(desc) > 1 and desc[-1] == "." and desc[-2] != ".":
            desc = desc[:-1].strip()
    return desc


class Project(BaseModel):
    """The partial ``pyproject.toml``'s ``[project]`` data model."""

    name: str
    classifiers: Sequence[str]


class PyProject(BaseModel):
    """The partial ``pyproject.toml`` data model."""

    project: Project


def load_project(path: os.PathLike[str] | None = None) -> Project:
    """
    Load the ``[project]`` section from ``pyproject.toml``.

    :param path: The path to the ``pyproject.toml`` file or similar
    :return: the ``[project]`` section
    :raises OSError: if the ``pyproject.toml`` file or similar cannot be opened
        for reading
    :raises ValueError: if the ``pyproject.toml`` file or similar is corrupted
    :raises pydantic.ValidationError: if the ``pyproject.toml`` file or similar
        is corrupted

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
    return PyProject.model_validate(load_toml(path)).project


def inside_ci() -> bool:
    """
    Return :obj:`True` if we are running inside CI.

    :return: :obj:`True` when running inside CI
    """
    return any(x in os.environ for x in CI_ENV_VARS)


def project_pythons() -> Sequence[str]:
    """
    Return the list of Python versions supported by the project.

    :return: the list of Python versions supported by the project
    """
    return [
        classifier.split()[-1]
        for classifier in load_project().classifiers
        if classifier.startswith("Programming Language :: Python :: 3.")
    ]


def dist_dir() -> os.PathLike[str]:
    """
    Return the path to the ``./dist`` directory.

    :return: the path to the ``./dist`` directory
    """
    return pathlib.Path.cwd() / "dist"


def run_script(session: Session, script: str) -> str:
    """
    Run the script under the session.

    :param session: The Nox session
    :param script: The script
    :return: the script output
    :raises nox.command.CommandFailed: when :xarg:`script` causes a failure
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
    return run_script(session, script).lower() == "true"


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
