#
# File:    ./src/vutils/nox/pkgspec.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-11 18:11:17 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Python package specification helpers."""

import enum
import functools
import pathlib
from typing import TYPE_CHECKING

from pkginfo import Wheel
from nox.project import load_toml

from vutils.nox.utils import is_installed, relative_path, resolve_path

if TYPE_CHECKING:
    from collections.abc import Iterable, MutableSequence
    import os
    from typing import Literal

    from nox.sessions import Session

    from vutils.nox import StrPath

#: Keywords
KW_NAME: Literal["name"] = "name"
KW_PROJECT: Literal["project"] = "project"


class DistKind(enum.IntEnum):
    """Python package distribution kind."""

    #: Source distribution, including editable
    SDIST: int = 1
    #: Binary distribution, e.g. wheel
    BDIST: int = 2


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

    #: The path to the package
    path: os.PathLike[str]
    #: The kind of the package distribution
    kind: DistKind
    #: Details discovered about the package, containing the real path to the
    #: package on the local file system and the name of the package
    __discovered: tuple[os.PathLike[str], str] | None

    __slots__ = ("path", "kind", "__discovered")

    def __init__(
        self, path: StrPath = ".", kind: DistKind = DistKind.SDIST
    ) -> None:
        """
        Initialize the instance.

        :param path: The path to the python package
        :param kind: The kind of the package distribution
        """
        self.path = pathlib.Path(path)
        self.kind = kind
        self.__discovered = None

    def __eq__(self, other: LocalDist) -> bool:
        """
        Test whether this object is equal to :xarg:`other`.

        :param other: The other instance the test is applied on
        :return: :obj:`True` if the distribution kinds of this object and the
            :xarg:`other` object are equal
        """
        return self.kind == other.kind

    def __lt__(self, other: LocalDist) -> bool:
        """
        Test whether this object is less than :xarg:`other`.

        :param other: The other instance the test is applied on
        :return: :obj:`True` if the distribution kind of this object is less
            than the distribution kind of :xarg:`other`
        """
        return self.kind < other.kind

    def discover(self, session: Session) -> tuple[os.PathLike[str], str]:
        """
        Discover the real path to the package and its name.

        :param session: The Nox session
        :return: the real path to the package and the distribution name of the
            package
        :raises ValueError: when the path from where the discovery should start
            is not an existing directory
        :raises ValueError: when more than one ``*.whl`` files were discovered

        The discovery prefers editable packages over wheels, that is if there
        are both ``pyproject.toml`` and ``*.whl`` in the same directory, the
        name and the path to the package are derived from this
        ``pyproject.toml`` and its location in the local file system.

        While discovering, only ``pyproject.toml`` and ``*.whl`` files are
        taken account. More than one ``*.whl`` file is treated as an error.
        """
        if self.__discovered:
            return self.__discovered
        self.path = resolve_path(self.path)
        if not self.path.is_dir():
            raise ValueError(f"`{self.path}` is not a directory")
        source: os.PathLike[str]
        name: str

        pyproject_toml: os.PathLike[str] = self.path / "pyproject.toml"
        if pyproject_toml.is_file():
            source = self.path
            name = load_toml(pyproject_toml)[KW_PROJECT][KW_NAME]
        else:
            wheels: Iterable[os.PathLike[str]] = self.path.glob("*.whl")
            if len(wheels) != 1:
                raise ValueError(
                    f"Exactly one *.whl is expected in `{self.path}`"
                )
            source = wheels[0]
            name = Wheel(source).name
        self.__discovered = (source, name)
        return self.__discovered

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
        source: os.PathLike[str]
        name: str

        source, name = self.discover(session)
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

    def remove(self, session: Session) -> None:
        """
        Remove this package.

        :param session: The Nox session
        """
        name: str

        _, name = self.discover(session)
        if not is_installed(session, name):
            return
        cmd: MutableSequence[StrPath] = (
            ["uv"] if session.venv_backend == "uv" else ["python", "-m"]
        )
        cmd.extend(["pip", "uninstall", name])
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
