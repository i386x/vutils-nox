#
# File:    ./src/vutils/nox/project.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-06-17 01:47:07 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Python project helpers."""

import functools
import os
import pathlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Self

from nox.project import load_toml
from nox.sessions import Session
from packaging.requirements import Requirement
from packaging.version import Version
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pyproject_metadata import StandardMetadata

from vutils.nox.utils import (
    EV_PYTHONPATH,
    IMPORT_ERROR_RE,
    resolve_path,
    run_script,
    setenv,
)

#: File names
PYPROJECT_TOML = "pyproject.toml"

#: Project metadata fields names
ATTR_KEY = "attr"
AUTHOR_EMAIL_KEY = "author_email"
AUTHOR_KEY = "author"
DESCRIPTION_KEY = "description"
DYNAMIC_KEY = "dynamic"
FILE_KEY = "file"
LICENSE_FILE_KEY = "license_file"
MAINTAINER_EMAIL_KEY = "maintainer_email"
MAINTAINER_KEY = "maintainer"
NAME_KEY = "name"
VERSION_KEY = "version"


class PyProjectProject(BaseModel):
    """The ``[project]`` section data model."""

    model_config = ConfigDict(strict=True)

    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ]
    version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ] = "0.0.0"
    dependencies: Sequence[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    ]
    license_files: Annotated[
        Sequence[
            Annotated[
                str,
                StringConstraints(strip_whitespace=True, min_length=1),
            ]
        ],
        Field(alias="license-files"),
    ]


class PyProjectDynamic(BaseModel):
    """The ``[tool.setuptools.dynamic]`` section data model."""

    model_config = ConfigDict(strict=True)

    version: (
        Annotated[
            Mapping[
                str,
                Annotated[
                    str,
                    StringConstraints(strip_whitespace=True, min_length=1),
                ],
            ],
            Field(min_length=1, max_length=1),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def check_dynamic_version(self) -> Self:
        """
        Validate :attr:`.PyProjectDynamic.version`.

        :return: self
        :raises ValueError: when :attr:`.PyProjectDynamic.version` is invalid
        """
        if self.version is None:
            return self
        for key in self.version.keys():
            if key not in (ATTR_KEY, FILE_KEY):
                raise ValueError(
                    f"Expected {ATTR_KEY} or {FILE_KEY}, found {key}"
                )
        return self


class PyProjectFind(BaseModel):
    """The ``[tool.setuptools.packages.find]`` section data model."""

    model_config = ConfigDict(strict=True)

    where: (
        Annotated[
            Sequence[
                Annotated[
                    str,
                    StringConstraints(strip_whitespace=True, min_length=1),
                ]
            ],
            Field(min_length=1),
        ]
        | None
    ) = None


class PyProjectPackages(BaseModel):
    """The ``[tool.setuptools.packages]`` section data model."""

    find: PyProjectFind | None = None


class PyProjectSetuptools(BaseModel):
    """The ``[tool.setuptools]`` data model."""

    dynamic: PyProjectDynamic | None = None
    packages: PyProjectPackages | None = None


class PyProjectTool(BaseModel):
    """The ``[tool]`` data model."""

    setuptools: PyProjectSetuptools | None = None


class PyProject(BaseModel):
    """The ``pyproject.toml`` data model."""

    project: PyProjectProject
    tool: PyProjectTool | None = None

    def __hash__(self) -> int:
        """
        Compute the hash.

        :return: the hash

        Currently it returns just this object's :func:`id` since this object is
        supposed to be read-only.
        """
        return id(self)


@functools.cache
def load_pyproject(path: os.PathLike[str] | None = None) -> PyProject:
    """
    Load ``pyproject.toml``.

    :param path: The path to the ``pyproject.toml``-like file or to the
        directory where the ``pyproject.toml`` file is present
    :return: the content of ``pyproject.toml``
    :raises OSError: when ``pyproject.toml`` cannot be opened for reading
    :raises pydantic.ValidationError: when ``pyproject.toml`` does not match
        its specification

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
    return PyProject.model_validate(load_toml(path))


@functools.cache
def get_metadata(pyproject: PyProject) -> StandardMetadata:
    """
    Extract metadata from the ``pyproject.toml`` content.

    :param pyproject: The content of the ``pyproject.toml``-like file
    :return: the metadata
    """
    return StandardMetadata.from_pyproject(pyproject.model_dump(by_alias=True))


@functools.cache
def get_name(pyproject: PyProject) -> str:
    """
    Get the value of ``project.name``.

    :param pyproject: The ``pyproject.toml`` data
    :return: the name of the project
    """
    return get_metadata(pyproject).name


@functools.cache
def get_version(pyproject: PyProject) -> Version:
    """
    Get the value of ``project.version``.

    :param pyproject: The ``pyproject.toml`` data
    :return: the project version
    """
    return get_metadata(pyproject).version


@functools.cache
def get_dependencies(pyproject: PyProject) -> Iterable[Requirement]:
    """
    Get the value of ``project.dependencies``.

    :param pyproject: The ``pyproject.toml`` data
    :return: the list of dependencies
    """
    return get_metadata(pyproject).dependencies


@functools.cache
def get_license_files(pyproject: PyProject) -> Iterable[os.PathLike[str]]:
    """
    Get the value of ``project.license-files``.

    :param pyproject: The ``pyproject.toml`` data
    :return: the list of license files
    """
    return get_metadata(pyproject).license_files


@functools.cache
def get_dynamic(pyproject: PyProject, field: str) -> tuple[str, str] | None:
    """
    Get the details about a dynamically specified field.

    :param pyproject: The ``pyproject.toml`` data
    :param field: The dynamically specified field name
    :return: the pair containing the directive name and the value associated
        with that directive or :obj:`None` if :xarg:`field` is not dynamic

    Get the value of :xarg:`field` from the ``tool.setuptools.dynamic``
    section. The first element of the returned pair is the name of a directive
    (either ``attr`` or ``file``) and the second element is the value
    associated with the directive (i.e. a fully qualified attribute name or a
    file name, respectively).
    """
    tool = pyproject.tool
    if tool is None:
        return None
    setuptools = tool.setuptools
    if setuptools is None:
        return None
    dynamic = setuptools.dynamic
    if dynamic is None:
        return None
    data: Mapping[str, str] | None = {
        VERSION_KEY: dynamic.version,
    }.get(field)
    if data is None:
        return None
    return next(iter(data.items()))


@functools.cache
def get_where(pyproject: PyProject) -> Iterable[str] | None:
    """
    Get the value of ``tool.setuptools.packages.find.where``.

    :param pyproject: The ``pyproject.toml`` data
    :return: the list of directories, relative to the ``pyproject.toml``-like
        file directory, where to look for packages to be distributed or
        :obj:`None` if no such list is specified
    """
    tool = pyproject.tool
    if tool is None:
        return None
    setuptools = tool.setuptools
    if setuptools is None:
        return None
    packages = setuptools.packages
    if packages is None:
        return None
    find = packages.find
    if find is None:
        return None
    return find.where


@functools.cache
def project_name() -> str:
    """
    Return the name of the project.

    :return: the name of the project
    """
    return get_name(load_pyproject())


@functools.cache
def project_pythons() -> Iterable[str]:
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
def project_dependencies() -> Iterable[str]:
    """
    Return the list of project dependencies.

    :return: the list of project dependencies
    """
    return get_dependencies(load_pyproject())


def resolve_dynamic_version(session: Session, pyproject: PyProject) -> Version:
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
    dynver = get_dynamic(pyproject, VERSION_KEY)
    if dynver is None:
        raise ValueError("Missing version")

    directive, value = dynver
    if directive == ATTR_KEY:
        parts = value.rsplit(".", 1)
        if len(parts) != 2:
            raise ValueError(f"`{value}` has no module name part")
        pypath: str | None = None
        where = get_where(pyproject)
        if where is not None:
            where = list(filter(None, where))
        if where:
            pypath = os.pathsep.join(where)
        with setenv(session, {EV_PYTHONPATH: pypath}):
            version = run_script(
                session, f"from {parts[0]} import {parts[1]} as x; print(x)"
            )
            if not version or IMPORT_ERROR_RE.search(version):
                raise ValueError(f"Invalid version: `{version}`")
            return Version(version)
    elif directive == FILE_KEY:
        path = resolve_path(value)
        if not path.is_file():
            raise OSError(f"`{path}` is not a file")
        with path.open(encoding="utf-8") as fobj:
            version = fobj.read().strip()
            if not version:
                raise ValueError("Invalid version (empty string)")
            return Version(version)
    else:
        raise ValueError(f"Invalid directive: `{directive}`")
