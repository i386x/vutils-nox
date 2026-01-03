#
# File:    ./src/vutils/nox/pkgspec.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-11 18:11:17 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Python package specification helpers."""

from collections.abc import Mapping, MutableSequence
import email.header
import enum
import functools
import importlib.metadata
import os
import pathlib
from typing import TYPE_CHECKING, Self

from nox.sessions import Session
from packaging.version import Version
from pkginfo import Wheel

from vutils.nox.utils import (
    DYNAMIC_KEY,
    EV_PYTHONPATH,
    KW_PYTHON,
    PYPROJECT_TOML,
    VERSION_KEY,
    dist_dir,
    envvar_is_unset,
    get_metadata,
    get_version,
    is_installed,
    is_installed_as_editable,
    is_mutable_mapping,
    load_pyproject,
    relative_path,
    resolve_dynamic_version,
    remove_build_artifacts,
)

if TYPE_CHECKING:
    from vutils.nox import StrPath

#: Selected metadata fields names
AUTHOR_EMAIL_KEY: str = "author"
AUTHOR_KEY: str = "author_email"
DESCRIPTION_KEY: str = "description"
MAINTAINER_EMAIL_KEY: str = "maintainer_email"
MAINTAINER_KEY: str = "maintainer"


def fix_version(
    metadata: object, session: Session, pyproject: Mapping[str, object]
) -> None:
    """
    Fix the project version.

    :param metadata: The metadata object containing the project or a
        distribution information
    :param session: The Nox session
    :param pyproject: The ``pyproject.toml`` data
    :raises TypeError: when the metadata object or the ``pyproject.toml`` data
        contain items with a wrong type
    :raises ValueError: when the ``pyproject.toml`` data or resolved dynamic
        data contain an item with an invalid value
    :raises OSError: when related files cannot be opened for reading
    """
    # If `version` is not `None`, `metadata` contains the most recent version
    if get_version(pyproject) is None:
        # If `version` is `None`, `metadata` contains a default version so we
        # need to patch it
        if not is_mutable_mapping(metadata, ("__setitem__",)):
            raise TypeError("Metadata are not a mutable mapping")
        metadata[VERSION_KEY] = resolve_dynamic_version(session, pyproject)


def fix_description(metadata: object) -> None:
    """
    Fix the ``description`` field in metadata.

    :param metadata: The metadata object containing the project or a
        distribution information
    :raises TypeError: when the metadata object is not a mutable mapping

    If ``description`` is empty, remove it from the metadata. This will ensure
    the compatibility between metadata obtained by different methods and from
    different sources.
    """
    if not is_mutable_mapping(
        metadata, ("__contains__", "__getitem__", "__delitem__")
    ):
        raise TypeError("Metadata must be a mutable mapping")
    if DESCRIPTION_KEY not in metadata:
        return
    if not metadata[DESCRIPTION_KEY]:
        del metadata[DESCRIPTION_KEY]


def fix_people(metadata: object) -> None:
    """
    Fix person-like fields in metadata.

    :param metadata: The metadata object containing the project or a
        distribution information
    :raises TypeError: when the metadata object is not a mutable mapping or a
        field has a wrong type

    In person-like fields (``author``, ``author_email``, ``maintainer``, and
    ``maintainer_email``) replace encoded data (``=?...?=``) with their
    origins. This will ensure the compatibility between metadata obtained by
    different methods and from different sources.
    """
    if not is_mutable_mapping(
        metadata, ("__contains__", "__getitem__", "__setitem__")
    ):
        raise TypeError("Metadata must be a mutable mapping")
    field: str
    for field in (
        AUTHOR_KEY, AUTHOR_EMAIL_KEY, MAINTAINER_KEY, MAINTAINER_EMAIL_KEY
    ):
        if field not in metadata:
            continue
        person: object = metadata[field]
        if not isinstance(person, str):
            raise TypeError(f"`{field}` must be a string")
        metadata[field] = str(
            email.header.make_header(email.header.decode_header(person))
        )


def remove_redundant(metadata: object) -> None:
    """
    Remove fields from metadata not needed for comparison.

    :param metadata: The metadata object containing the project or a
        distribution information
    :raises TypeError: when the metadata object is not a mutable mapping

    This will ensure the compatibility between metadata obtained by different
    methods and from different sources.
    """
    if not is_mutable_mapping(metadata, ("__contains__", "__delitem__")):
        raise TypeError("Metadata must be a mutable mapping")
    if DYNAMIC_KEY in metadata:
        del metadata[DYNAMIC_KEY]


class Metadata:
    """The project or a distribution metadata wrapper."""

    #: The metadata object in JSON
    metadata: object

    __slots__ = ("metadata",)

    def __init__(self, metadata: object | None = None) -> None:
        """
        Initialize the wrapper.

        :param metadata: The metadata object containing the project or a
            distribution information
        """
        if metadata is None:
            metadata = {}
        self.metadata = metadata

    @classmethod
    def from_pyproject(
        cls, session: Session, path: os.PathLike[str] | None = None
    ) -> Self:
        """
        Load metadata from the ``pyproject.toml``-like file.

        :param session: The Nox session
        :param path: The path to the ``pyproject.toml``-like file or to the
            directory where the ``pyproject.toml`` file is present
        :return: the instance of :class:`~.Metadata` initialized with the
            loaded and processed metadata
        :raises TypeError: when the loaded metadata contain items with a wrong
            type
        :raises ValueError: when an item from the loaded metadata have an
            invalid value
        :raises OSError: when a requested file cannot be opened for reading
        """
        pyproject: Mapping[str, object] = load_pyproject(path)
        metadata: object = get_metadata(pyproject).as_json()
        fix_version(metadata, session, pyproject)
        fix_description(metadata)
        fix_people(metadata)
        remove_redundant(metadata)
        return cls(metadata)

    @classmethod
    def from_distribution(cls, name: str) -> Self:
        """
        Load metadata from the distribution.

        :param name: The name of the installed package
        :return: the instance of :class:`~.Metadata` initialized with the
            loaded and processed metadata
        :raises ~importlib.metadata.PackageNotFoundError: when the package is
            not present inside the distribution
        :raises TypeError: when the loaded metadata contain items with a wrong
            type
        """
        metadata: object = importlib.metadata.distribution(name).metadata.json
        fix_description(metadata)
        fix_people(metadata)
        remove_redundant(metadata)
        return cls(metadata)

    def __eq__(self, other: Self) -> bool:
        """
        Compare two metadata wrappers for equality.

        :param other: The other metadata wrapper used for the comparison
        :return: :obj:`True` if this instance is equal to :xarg:`other`

        Two metadata wrappers are equal if and only if their underlying
        metadata objects are equal.

        Two metadata objects are equal if all these conditions are satisfied:

        * they are both mappings with the same content
        * if they are referencing files, these files must be also identical
        """


class DistKind(enum.IntEnum):
    """Python package distribution kind."""

    #: Editable
    EDITABLE: int = 1
    #: Wheel
    WHEEL: int = 2


def swap_kind(kind: DistKind) -> DistKind:
    """
    Swap kind.

    :param kind: The kind
    :return: the kind opposite to :xarg:`kind`
    """
    return DistKind.EDITABLE if kind == DistKind.WHEEL else DistKind.WHEEL


class InstallMode(enum.IntEnum):
    """Installation mode."""

    #: Do not install dependencies if they are already installed
    NOINSTALL: int = 0
    #: Reinstall dependencies
    REINSTALL: int = 1
    #: Force reinstall dependencies
    FORCE: int = 2


@functools.total_ordering
class LocalDist:
    """Python package distribution on the local file system."""

    #: The preferred kind of the package distribution to be installed
    kind: DistKind
    #: The discovered name of the local package distribution
    __name: str | None
    #: The discovered wheel
    __wheel: os.PathLike[str] | None

    __slots__ = ("kind", "__name", "__wheel")

    def __init__(self, kind: DistKind = DistKind.EDITABLE) -> None:
        """
        Initialize the instance.

        :param kind: The kind of the package distribution
        """
        self.kind = kind
        self.__name = None
        self.__wheel = None

    def __eq__(self, other: Self) -> bool:
        """
        Test whether this object is equal to :xarg:`other`.

        :param other: The other instance the test is applied on
        :return: :obj:`True` if the distribution kinds of this object and the
            :xarg:`other` object are equal
        """
        return self.kind == other.kind

    def __lt__(self, other: Self) -> bool:
        """
        Test whether this object is less than :xarg:`other`.

        :param other: The other instance the test is applied on
        :return: :obj:`True` if the distribution kind of this object is less
            than the distribution kind of :xarg:`other`
        """
        return self.kind < other.kind

    def __discover_name(self) -> None:
        """Discover the name of the local package distribution."""
        if self.__name:
            return
        pyproject_toml: os.PathLike[str] = pathlib.Path.cwd() / PYPROJECT_TOML
        if pyproject_toml.is_file():
            self.__name = load_project(pyproject_toml).name

    def discover(self) -> None:
        """
        Discover installable local package distributions.

        :raises ValueError: when no installable local package distributions
            were discovered

        Find all wheels inside ``./dist`` directory, select the one with the
        highest version. If there are more candidates, it is unspecified which
        one is selected.
        """
        self.__discover_name()
        if self.__name is None:
            raise ValueError("Missing the local package distribution name")
        if self.__wheel:
            return
        path: os.PathLike[str] = dist_dir()
        if not path.is_dir():
            return

        wheels: MutableSequence[tuple[os.PathLike[str], Wheel]] = []
        whl: os.PathLike[str]
        for whl in path.glob("*.whl"):
            wheel: Wheel = Wheel(whl)
            if wheel.name is None or wheel.name != self.__name:
                continue
           wheels.append((whl, wheel))

        def keyfunc(item: tuple[os.PathLike[str], Wheel]) -> Version:
            """
            Convert an item to the comparable object.

            :param item: The item
            :return: the comparable object
            """
            ver: str | None = item[1].version
            return Version("0.0.0" if ver is None else ver)

        wheels.sort(key=keyfunc)
        if len(wheels) == 0:
            raise ValueError(f"No matching *.whl found at `{path}`")
        self.__wheel = wheels[-1][0]

    def resolve_conflicts(self, session: Session) -> None:
        """
        Resolve potential conflicts before installation.

        :param session: The Nox session

        First, remove all possible artifacts produced during ``python -m
        build`` and ensure ``PYTHONPATH`` is not set. This excludes packages
        outside the Python virtual environment while querying for installed
        packages. Next, remove the old package if it was installed from the
        different kind of distribution.
        """
        remove_build_artifacts()
        envvar_is_unset(session, EV_PYTHONPATH)
        self.remove(session, swap_kind(self.__kind))

    def install(
        self, session: Session, mode: InstallMode = InstallMode.NOINSTALL
    ) -> None:
        """
        Install the local package.

        :param session: The Nox session
        :param mode: The installation mode

        Depending on how this package was discovered, it is installed either as
        a wheel or as an editable.
        """
        self.discover()
        self.resolve_conflicts(session)

        if mode == InstallMode.FORCE:
            self.remove(session)
        if mode == InstallMode.NOINSTALL and is_installed(session, name):
            return
        args: MutableSequence[StrPath] = [relative_path(source)]
        if session.venv_backend == "uv" and source.is_file():
            args[0] = f"{name}@{args[0]}"
            args.insert(0, "--reinstall-package")
        if source.is_dir():
            args.insert(0, "-e")
        if mode == InstallMode.FORCE:
            args.insert(0, "--force-reinstall")
        session.install(*args, silent=False)

    def remove(self, session: Session, kind: DistKind | None = None) -> None:
        """
        Remove this package if it is of the specified kind.

        :param session: The Nox session
        :param kind: The kind of distribution of this package
        :raises ValueError: when the name of this package is not known

        If the kind is not given the value passed during this object's
        initialization is used. If the distribution kind is specified as
        editable, the package is removed only if it has been installed as
        editable. Analogously for wheels.
        """
        self.__discover_name()
        if self.__name is None:
            raise ValueError("Missing the local package distribution name")
        if kind is None:
            kind = self.__kind
        if not is_installed(session, self.__name):
            return
        if (
            is_installed_as_editable(session, self.__name)
            is not (kind == DistKind.EDITABLE)
        ):
            return
        cmd: MutableSequence[StrPath] = (
            ["uv"] if session.venv_backend == "uv" else [KW_PYTHON, "-m"]
        )
        cmd.extend(["pip", "uninstall", "-y", self.__name])
        session.run(*cmd)

    def __call__(
        self, session: Session, mode: InstallMode = InstallMode.NOINSTALL
    ) -> None:
        """
        Install the local package.

        :param session: The Nox session
        :param mode: The installation mode

        This is the alias to :meth:`~.LocalDist.install`.
        """
        self.install(session, mode)


class Security:
    """Marker telling that a dependency is a security update."""

    #: The dependency specifier
    __specifier: str

    __slots__ = ("__specifier",)

    def __init__(self, specifier: str) -> None:
        """
        Initialize the marker instance.

        :param specifier: The dependency specifier
        """
        self.__specifier = specifier.strip()

    def __str__(self) -> str:
        """
        Return the specifier.

        :return: the specifier
        """
        return self.__specifier
