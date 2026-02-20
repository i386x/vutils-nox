#
# File:    ./src/vutils/nox/pkgspec.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-11 18:11:17 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Python package specification helpers."""

import email.header
import enum
import functools
import os
import pathlib
from collections.abc import Iterable, Mapping, MutableSequence, Sequence
from typing import TYPE_CHECKING, Literal, Self

from nox.sessions import Session
from packaging.version import Version
from pkginfo import Wheel
from vutils.nox.utils import (
    DYNAMIC_KEY,
    EV_PYTHONPATH,
    KW_PYTHON,
    VERSION_KEY,
    compare_files,
    dist_dir,
    envvar_is_unset,
    get_license_files,
    get_metadata,
    get_metadata_from_pkg,
    get_pkg_metadata_dir,
    get_version,
    is_installed,
    is_installed_as_editable,
    is_mapping,
    is_mutable_mapping,
    load_pyproject,
    log_diff,
    relative_path,
    remove_build_artifacts,
    resolve_dynamic_version,
)

if TYPE_CHECKING:
    from vutils.nox import StrPath

#: Selected metadata fields names
AUTHOR_EMAIL_KEY: str = "author"
AUTHOR_KEY: str = "author_email"
DESCRIPTION_KEY: str = "description"
LICENSE_FILE_KEY: str = "license_file"
MAINTAINER_EMAIL_KEY: str = "maintainer_email"
MAINTAINER_KEY: str = "maintainer"
NAME_KEY: str = "name"

#: Keywords
KW_ALL: Literal["all"] = "all"


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
    """
    # If `version` is not `None`, `metadata` contains the most recent version
    if get_version(pyproject) is None:
        # If `version` is `None`, `metadata` contains a default version so we
        # need to patch it
        if not is_mutable_mapping(metadata):
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
    if not is_mutable_mapping(metadata):
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
    if not is_mutable_mapping(metadata):
        raise TypeError("Metadata must be a mutable mapping")
    field: str
    for field in (
        AUTHOR_KEY,
        AUTHOR_EMAIL_KEY,
        MAINTAINER_KEY,
        MAINTAINER_EMAIL_KEY,
    ):
        if field not in metadata:
            continue
        person: object = metadata[field]
        if not isinstance(person, str):
            raise TypeError(f"`{field}` must be a string")
        metadata[field] = str(
            email.header.make_header(email.header.decode_header(person))
        )


def fix_license_file(metadata: object) -> None:
    """
    Fix the ``license_field`` in metadata.

    :param metadata: The metadata object containing the project or a
        distribution information
    :raises TypeError: when the metadata object is not a mutable mapping

    If the ``license_field`` has a :class:`str` type, wrap it into a list.
    """
    if not is_mutable_mapping(metadata):
        raise TypeError("Metadata must be a mutable mapping")
    if LICENSE_FILE_KEY in metadata:
        license_file: object = metadata[LICENSE_FILE_KEY]
        if isinstance(license_file, str):
            metadata[LICENSE_FILE_KEY] = [license_file]


def remove_redundant(metadata: object) -> None:
    """
    Remove fields from metadata not needed for comparison.

    :param metadata: The metadata object containing the project or a
        distribution information
    :raises TypeError: when the metadata object is not a mutable mapping

    This will ensure the compatibility between metadata obtained by different
    methods and from different sources.
    """
    if not is_mutable_mapping(metadata):
        raise TypeError("Metadata must be a mutable mapping")
    if DYNAMIC_KEY in metadata:
        del metadata[DYNAMIC_KEY]


class Metadata:
    """The project or a distribution metadata wrapper."""

    #: The metadata object in JSON
    metadata: Mapping[object, object]
    #: The origin from which metadata were extracted
    origin: Mapping[object, object] | str

    __slots__ = ("metadata", "origin")

    def __init__(
        self, metadata: object, origin: Mapping[object, object] | str
    ) -> None:
        """
        Initialize the wrapper.

        :param metadata: The metadata object containing the project or a
            distribution information
        :param origin: The origin from which metadata were extracted
        :raises TypeError: when the metadata object is not a mapping
        """
        if not is_mapping(metadata):
            raise TypeError("Metadata must be a mapping")
        self.metadata = metadata
        self.origin = origin

    @property
    def name(self) -> str:
        """
        Get the project name.

        :return: the project name
        :raises KeyError: when there is no project name in metadata
        :raises TypeError: when the project name is not a string
        """
        if NAME_KEY not in self.metadata:
            raise KeyError(f"No `{NAME_KEY}` in metadata")
        name: object = self.metadata[NAME_KEY]
        if not isinstance(name, str):
            raise TypeError(f"`{NAME_KEY}` must be a string")
        return name

    @property
    def version(self) -> Version:
        """
        Get the project version.

        :return: the project version
        :raises TypeError: when the project version is not a string
        """
        if VERSION_KEY not in self.metadata:
            return Version("0.0.0")
        version: object = self.metadata[VERSION_KEY]
        if not version:
            return Version("0.0.0")
        if not isinstance(version, str):
            raise TypeError(f"`{VERSION_KEY}` must be a string")
        return Version(version)

    @classmethod
    def from_pyproject(
        cls, session: Session, path: os.PathLike[str] | None = None
    ) -> Self:
        """
        Load metadata from the ``pyproject.toml``-like file.

        :param session: The Nox session
        :param path: The path to the ``pyproject.toml``-like file or to the
            directory where the ``pyproject.toml`` file is present
        :return: the instance of :class:`.Metadata` initialized with the loaded
            and processed metadata
        """
        pyproject: Mapping[str, object] = load_pyproject(path)
        metadata: object = get_metadata(pyproject).as_json()
        fix_version(metadata, session, pyproject)
        fix_description(metadata)
        fix_people(metadata)
        fix_license_file(metadata)
        remove_redundant(metadata)
        return cls(metadata, pyproject)

    @classmethod
    def from_distribution(cls, session: Session, name: str) -> Self:
        """
        Load metadata from the distribution.

        :param session: The Nox session
        :param name: The name of the installed package
        :return: the instance of :class:`.Metadata` initialized with the loaded
            and processed metadata
        """
        metadata: object = get_metadata_from_pkg(session, name)
        fix_description(metadata)
        fix_people(metadata)
        fix_license_file(metadata)
        remove_redundant(metadata)
        return cls(metadata, name)

    def license_files(self, session: Session) -> Sequence[os.PathLike[str]]:
        """
        Gather license files.

        :param session: The Nox session
        :return: the list of license files
        :raises OSError: when the directory layout requirements were not met
        """
        if isinstance(self.origin, str):
            licenses_dir: os.PathLike[str] = (
                get_pkg_metadata_dir(session, self.origin) / "licenses"
            )
            if not licenses_dir.is_dir():
                raise OSError(f"`{licenses_dir}` is not a directory")
            result: MutableSequence[os.PathLike[str]] = []
            item: os.PathLike[str]
            for item in licenses_dir.iterdir():
                if item.is_dir():
                    raise OSError(f"Directory between licenses: `{item}`")
                result.append(item)
            return result
        else:
            globs: Iterable[str] = get_license_files(self.origin)
            result: MutableSequence[os.PathLike[str]] = []
            pattern: str
            for pattern in globs:
                item: os.PathLike[str]
                for item in pathlib.Path.cwd().glob(pattern):
                    if item.is_dir():
                        raise OSError(f"Directory between licenses: `{item}`")
                    result.append(item)
            return result

    def is_equal_to(self, session: Session, other: Self) -> bool:
        """
        Compare two metadata wrappers for equality.

        :param session: The Nox session
        :param other: The other metadata wrapper used for the comparison
        :return: :obj:`True` if this instance is equal to :xarg:`other`

        Two metadata wrappers are equal if and only if their underlying
        metadata objects are equal.

        Two metadata objects are equal if all these conditions are satisfied:

        * they are both mappings with the same content
        * if they are referencing files, these files must be also identical
        """
        if other is self:
            return True
        if self.metadata != other.metadata:
            log_diff(self.metadata, other.metadata)
            return False
        return compare_files(
            self.license_files(session),
            other.license_files(session),
        )


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
    #: Update dependencies
    UPDATE: int = 1
    #: Force reinstall dependencies
    FORCE: int = 2


class Installed(enum.IntEnum):
    """How a package is installed."""

    #: A package is not installed
    NOT_INSTALLED: int = 0
    #: A package is installed from wheel
    WHEEL: int = 1
    #: A package is installed as editable
    EDITABLE: int = 2


def wheel_version(path: os.PathLike[str] | None) -> Version:
    """
    Get the wheel version.

    :param path: The path to the wheel
    :return: the wheel version
    """
    if path is None:
        return Version("0.0.0")
    version: str | None = Wheel(path).version
    if version is None:
        version = "0.0.0"
    return Version(version)


def package_version(session: Session, package: str) -> Version:
    """
    Get the installed package version.

    :param session: The Nox session
    :param package: The package name
    :return: the package version
    """
    return Metadata.from_distribution(session, package).version


@functools.total_ordering
class LocalDist:
    """Python package distribution on the local file system."""

    #: The preferred kind of the package distribution to be installed
    kind: DistKind
    #: The discovered metadata of the local package distribution
    __metadata: Metadata | None
    #: The discovered wheel
    __wheel: os.PathLike[str] | None

    __slots__ = ("kind", "__metadata", "__wheel")

    def __init__(self, kind: DistKind = DistKind.EDITABLE) -> None:
        """
        Initialize the instance.

        :param kind: The kind of the package distribution
        """
        self.kind = kind
        self.__metadata = None
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

    def discover(self, session: Session) -> None:
        """
        Discover installable local package distributions.

        :param session: The Nox session
        :raises ValueError: when no installable local package distributions
            were discovered

        Find all wheels inside ``./dist`` directory, select the one with the
        highest version. If there are more candidates, it is unspecified which
        one is selected.
        """
        if self.__metadata is None:
            self.__metadata = Metadata.from_pyproject(session)
        if self.__wheel:
            return
        path: os.PathLike[str] = dist_dir()
        if not path.is_dir():
            return

        wheels: MutableSequence[tuple[os.PathLike[str], Wheel]] = []
        whl: os.PathLike[str]
        for whl in path.glob("*.whl"):
            wheel: Wheel = Wheel(whl)
            if wheel.name is None or wheel.name != self.__metadata.name:
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

    def install(
        self, session: Session, mode: InstallMode = InstallMode.NOINSTALL
    ) -> None:
        """
        Install the local package.

        :param session: The Nox session
        :param mode: The installation mode
        :raises ValueError: when the local package has no metadata or when a
            wheel has to be installed but there is no one

        Depending on how this package was discovered, it is installed either as
        a wheel or as an editable.

        If the package is already installed, :xarg:`mode` is taken account and
        the following logic applies:

        * If :xarg:`mode` is :attr:`.InstallMode.NOINSTALL` and the package is
          editable, the package is reinstalled only when its metadata have
          changed.
        * If :xarg:`mode` is :attr:`.InstallMode.UPDATE` and the package is a
          wheel, the package is reinstalled only if its version is greater than
          the version of its currently installed predecessor. If the package is
          editable it is always reinstalled.
        * If :xarg:`mode` is :attr:`.InstallMode.FORCE`, the package is
          reinstalled.
        * In a situation different from the above the package is left intact.
        """
        self.remove(session, swap_kind(self.kind))

        if self.__metadata is None:
            raise ValueError("Missing the local package metadata")
        name: str = self.__metadata.name

        installed: Installed = Installed.NOT_INSTALLED
        if is_installed(session, name):
            installed = Installed.WHEEL
        if installed > Installed.NOT_INSTALLED and is_installed_as_editable(
            session, name
        ):
            installed = Installed.EDITABLE

        if installed == Installed.EDITABLE:
            if (
                mode == InstallMode.NOINSTALL
                and not self.__metadata.is_equal_to(
                    session, Metadata.from_distribution(session, name)
                )
            ):
                mode = InstallMode.FORCE
            if mode == InstallMode.NOINSTALL:
                return
        elif installed == Installed.WHEEL:
            if mode == InstallMode.NOINSTALL:
                return
            if wheel_version(self.__wheel) > package_version(session, name):
                mode = InstallMode.FORCE
            if mode < InstallMode.FORCE:
                return

        if installed > Installed.NOT_INSTALLED:
            self.remove(session)

        args: MutableSequence[StrPath] = []
        if self.kind == DistKind.EDITABLE:
            args.extend(["-e", "."])
        else:
            if self.__wheel is None:
                raise ValueError("No wheel found to be installed")
            arg: str = f"{relative_path(self.__wheel)}"
            if session.venv_backend == "uv":
                arg = f"{name}@{arg}"
            args.append(arg)
        session.install(*args, silent=False)

    def remove(
        self, session: Session, kind: DistKind | Literal["all"] | None = None
    ) -> None:
        """
        Remove this package if it is of the specified kind.

        :param session: The Nox session
        :param kind: The kind of distribution of this package
        :raises ValueError: when the local package has no metadata

        If the kind is not given, the value passed during this object's
        initialization is used. If the distribution kind is specified as
        editable, the package is removed only if it has been installed as
        editable. Analogously for wheels. If the kind is set to ``"all"``, the
        package is removed no matter how it has been installed.
        """
        remove_build_artifacts()
        envvar_is_unset(session, EV_PYTHONPATH)
        self.discover(session)
        if self.__metadata is None:
            raise ValueError("Missing the local package metadata")
        name: str = self.__metadata.name
        if kind is None:
            kind = self.kind
        if not is_installed(session, name):
            return
        if not kind == KW_ALL:
            if is_installed_as_editable(session, name) is not (
                kind == DistKind.EDITABLE
            ):
                return
        cmd: MutableSequence[StrPath] = (
            ["uv"] if session.venv_backend == "uv" else [KW_PYTHON, "-m"]
        )
        cmd.extend(["pip", "uninstall", "-y", name])
        session.run(*cmd)

    def __call__(
        self, session: Session, mode: InstallMode = InstallMode.NOINSTALL
    ) -> None:
        """
        Install the local package.

        :param session: The Nox session
        :param mode: The installation mode

        This is the alias to :meth:`.LocalDist.install`.
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
