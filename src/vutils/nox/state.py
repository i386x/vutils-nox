#
# File:    ./src/vutils/nox/state.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-06-22 01:53:02 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""The command state."""

import configparser
import hashlib
import os
from collections.abc import Iterable, Mapping, MutableMapping, MutableSequence
from typing import TYPE_CHECKING, Annotated, Generator, Literal, Self, TypeVar

from nox.logger import logger
from nox.sessions import Session
from nox.virtualenv import CondaEnv, VirtualEnv
from pydantic import BaseModel, StringConstraints
from tomli_w import dump as toml_dump

from vutils.nox.pkgspec import InstallMode, LocalDist, Security
from vutils.nox.utils import DANGER_ENV_VARS, data2str, mergeinsert, setenv

if TYPE_CHECKING:
    from vutils.nox.command import Command
    from vutils.nox.typing import ConfType, PkgSpecType

T = TypeVar("T", bound=Security | str)

#: Parameters, keys, and properties
KW_CONF: Literal["conf"] = "conf"
KW_DEPS: Literal["deps"] = "deps"


class CommandStateData(BaseModel):
    """The :class:`.CommandState` data model."""

    # Command name to checksum mappings
    dependencies: MutableMapping[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)],
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)],
    ]
    configuration: MutableMapping[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)],
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)],
    ]


class CommandState:
    """Persistent command state shared between runs."""

    #: The name of the file that serves as the persistent storage
    __name: str
    #: The path to the persistent storage
    __storage: os.PathLike[str] | None
    #: The data reflecting the command state
    __data: CommandStateData

    __slots__ = ("__name", "__storage", "__data")

    def __init__(self, name: str) -> None:
        """
        Initialize the command state.

        :param name: The name of the persistent storage
        """
        self.__name = name
        self.__storage = None
        self.__data = CommandStateData(dependencies={}, configuration={})

    def __get_storage(self, session: Session) -> os.PathLike[str]:
        """
        Get the path to the persistent storage.

        :param session: The Nox session
        :return: the path to the persistent storage
        """
        if not self.__storage:
            self.__storage = session.cache_dir / self.__name
        return self.__storage

    def load(self, session: Session) -> None:
        """
        Load the data from the persistent storage.

        :param session: The Nox session

        By calling this method changes made so far are discarded and replaced
        with the recent data from the persistent storage.
        """
        if (
            isinstance(session.virtualenv, (CondaEnv, VirtualEnv))
            and not session.virtualenv.reuse_existing
        ):
            logger.info("state %s cleared", self.__name)
            return
        storage = self.__get_storage(session)
        if not storage.is_file():
            return
        with storage.open() as fobj:
            self.__data = CommandStateData.model_validate_json(
                fobj.read(), strict=True
            )

    def store(self, session: Session) -> None:
        """
        Store the data to the persistent storage.

        :param session: The Nox session
        """
        storage = self.__get_storage(session)

        with storage.open("w") as fobj:
            fobj.write(self.__data.model_dump_json(warnings="error"))

    def changed_deps(self, command: "Command") -> bool:
        """
        Check whether the set of packages to install has been changed.

        :param command: The command
        :return: :obj:`True` if the set of packages associated with
            :xarg:`command` has been changed
        """

        def callback(cmd: "Command") -> None:
            """
            Gather the state of :xarg:`cmd`'s dependencies.

            :param cmd: The command
            """
            cmd.changed(KW_DEPS)

        # Gather the state of subcommands' dependencies ...
        command.traverse(callback)
        # ... and then of command's ones
        cmd2sum = self.__data.dependencies
        new_checksum = command.checksum(KW_DEPS)
        changed = command.name not in cmd2sum
        checksum = cmd2sum.setdefault(command.name, new_checksum)
        logger.info(
            "DEPENDENCIES: %s: %s (%s)",
            command.name,
            new_checksum,
            (
                "added"
                if changed
                else (
                    f"changed from {checksum}"
                    if new_checksum != checksum
                    else "unchanged"
                )
            ),
        )
        if new_checksum != checksum:
            cmd2sum[command.name] = new_checksum
            return True
        return changed

    def changed_conf(self, command: "Command") -> bool:
        """
        Check whether the configuration has been changed.

        :param command: The command
        :return: :obj:`True` if the configuration associated with
            :xarg:`command` has been changed
        """
        config = command.config()
        if config is None:
            return False
        cfg2sum = self.__data.configuration
        new_checksum = command.checksum(KW_CONF)
        changed = config not in cfg2sum
        checksum = cfg2sum.setdefault(config, new_checksum)
        logger.info(
            "CONFIGURATION: %s: %s (%s)",
            config,
            new_checksum,
            (
                "added"
                if changed
                else (
                    f"changed from {checksum}"
                    if new_checksum != checksum
                    else "unchanged"
                )
            ),
        )
        if new_checksum != checksum:
            cfg2sum[config] = new_checksum
            return True
        return changed


class Container:
    """Base class for dependencies and configuration containers."""

    #: The container data checksum
    __checksum: str | None

    __slots__ = ("__checksum",)

    def __init__(self) -> None:
        """Initialize the container."""
        self.__checksum = None

    def add(self, name: str, item: object) -> None:
        """
        Add an item to the container.

        :param name: The name of the item
        :param item: The item to be stored under the :xarg:`name`
        """
        raise NotImplementedError

    def commit(self) -> None:
        """
        Commit the changes made to the container.

        This may be necessary to trigger the update of the internal state of
        the container.
        """
        self.__checksum = None
        self.checksum()

    def items(self) -> Generator[str, None, None]:
        """
        Yield items needed to compute the container data checksum.

        :return: the generator yielding items suitable for the container data
            checksum computation
        """
        raise NotImplementedError

    def checksum(self) -> str:
        """
        Compute the checksum of the container data.

        :return: the checksum of the container data
        """
        if not self.__checksum:
            hasher = hashlib.new("sha512")

            for item in self.items():
                hasher.update(item.encode())
            self.__checksum = hasher.hexdigest()
        return self.__checksum


def add_deps_to(
    container: "Dependencies", deps: Mapping[str, Iterable[T]], kind: T
) -> None:
    """
    Add dependencies to the container.

    :param container: The container to store dependencies in
    :param deps: Dependencies
    :param kind: The dummy dependency from which the dependency type is derived
        in case :xarg:`deps` contains an item with the empty list of specifiers
        (this is needed to distinct between an update and ordinary dependency)
    """
    for pkg in deps:
        for spec in deps[pkg]:
            container.add(pkg, spec)
        container.add(pkg, kind)


class Dependencies(Container):
    """Python package dependencies container."""

    #: Updates (these will be prioritized over ordinary dependencies)
    __updates: MutableMapping[str, Iterable[Security]]
    #: Ordinary dependencies
    __main: MutableMapping[str, Iterable[str]]
    #: A local Python package distribution
    __local: LocalDist | None
    #: All dependencies converted to arguments passable to the Python package
    #: installer
    __install_args: MutableSequence[str]

    __slots__ = ("__updates", "__main", "__local", "__install_args")

    def __init__(self) -> None:
        """Initialize the container."""
        Container.__init__(self)
        self.__updates = {}
        self.__main = {}
        self.__local = None
        self.__install_args = []

    def add(self, name: str, item: "PkgSpecType") -> None:
        """
        Add a dependency to the container.

        :param name: The Python package name
        :param item: The Python package specifier
        :raises ValueError: when invoked with invalid combination of
            :xarg:`name` and :xarg:`item`

        When :xarg:`item` is :obj:`None`, nothing happens.

        When :xarg:`item` is an instance of
        :class:`~vutils.nox.pkgspec.Security`, :xarg:`name` is classified as an
        update.

        When :xarg:`item` is an instance of :class:`str`, :xarg:`name` is
        classified as an ordinary dependency.

        Finally, when :xarg:`item` is an instance of
        :class:`~vutils.nox.pkgspec.LocalDist`, :xarg:`name` is classified as
        a local distribution (source or binary) and it must be ``.``. When both
        source and binary distributions are added as dependencies, the binary
        distribution is selected for installation.

        :class:`~vutils.nox.pkgspec.LocalDist` as :xarg:`item` can be combined
        only with ``.`` as :xarg:`name` and vice versa. Other combinations lead
        to :exc:`ValueError`.
        """
        if item is None:
            return
        if name == "." and not isinstance(item, LocalDist):
            detail = (
                "The `.` package name is reserved for locally distributed"
                " packages only"
            )
            raise ValueError(detail)
        if isinstance(item, Security):
            self.__updates.setdefault(name, [])
            if str(item):
                self.__updates[name].append(item)
        elif isinstance(item, str):
            item = item.strip()
            self.__main.setdefault(name, [])
            if item:
                self.__main[name].append(item)
        elif isinstance(item, LocalDist):
            if name != ".":
                detail = (
                    "Locally distributed packages should be named `.` ("
                    f"`{name}` given)"
                )
                raise ValueError(detail)
            if self.__local is None or self.__local <= item:
                self.__local = item

    def add_myself_to(self, container: Self) -> None:
        """
        Add the content of this container to :xarg:`container`.

        :param container: The other container
        """
        add_deps_to(container, self.__updates, Security(""))
        add_deps_to(container, self.__main, "")
        if self.__local:
            container.add(".", self.__local)

    def commit(self) -> None:
        """
        Commit changes made to the container.

        This will compute the install arguments and trigger the checksum
        computation.
        """
        self.__install_args.clear()

        for depset in (self.__updates, self.__main):
            for pkg, specs in depset.items():
                if specs:
                    self.__install_args.extend(
                        [f"{pkg} {spec}" for spec in specs]
                    )
                else:
                    self.__install_args.append(pkg)
        Container.commit(self)

    def items(self) -> Generator[str, None, None]:
        """
        Yield install arguments.

        :return: the generator yielding install arguments

        The checksum of the dependencies container is computed from the
        arguments passed to the Python package installer.
        """
        yield from self.__install_args

    def install(
        self,
        session: Session,
        command: "Command",
        mode: InstallMode = InstallMode.NOINSTALL,
    ) -> None:
        """
        Install dependencies held by this container.

        :param session: The Nox session
        :param command: The command owning this container
        :param mode: The installation mode
        """
        with setenv(session, DANGER_ENV_VARS):
            if self.__local:
                self.__local.install(session, mode=mode)
            if (
                command.changed(KW_DEPS) or mode > InstallMode.NOINSTALL
            ) and self.__install_args:
                if mode == InstallMode.UPDATE:
                    self.__install_args.insert(0, "-U")
                elif mode == InstallMode.FORCE:
                    self.__install_args.insert(0, "--force-reinstall")
                session.install(*self.__install_args, silent=False)


class Configuration(Container):
    """Configuration container."""

    #: The configuration data
    __data: "ConfType"

    __slots__ = ("__data",)

    def __init__(self) -> None:
        """Initialize the container."""
        Container.__init__(self)
        self.__data = {}

    def add(self, name: str, item: object) -> None:
        """
        Add a configuration item.

        :param name: The configuration item name
        :param item: The configuration item itself
        """
        mergeinsert(self.__data, item, name)

    def items(self) -> Generator[str, None, None]:
        """
        Yield configuration converted to :class:`str`.

        :return: the generator that yields configuration converted to
            :class:`str` from which the checksum of this container is computed
        """
        yield from data2str(self.__data)

    def __write_config(self, path: os.PathLike[str]) -> None:
        """
        Dump the configuration to the file.

        :param path: The path to the file to which the configuration is going
            to be stored
        :raises ValueError: when the configuration format, derived from the
            suffix or the name of the configuration file, is not supported

        A file with no suffix whose name ends with ``rc`` is treated as INI
        file.
        """
        suffix = path.suffix
        if suffix == ".toml":
            with path.open("wb") as fobj:
                toml_dump(self.__data, fobj)
        elif suffix in (".cfg", ".ini") or path.name.endswith("rc"):
            parser = configparser.ConfigParser()
            parser.read_dict(self.__data)
            with path.open("w") as fobj:
                parser.write(fobj)
        else:
            raise ValueError(f"{path.name}: Format is not supported")

    def config(self, command: "Command") -> os.PathLike[str]:
        """
        Prepare and get the configuration file for the command.

        :param command: The command
        :return: the path to the configuration file
        :raises ValueError: when the name of the configuration file cannot be
            retrieved from the command
        """
        config = command.config()
        if config is None:
            raise ValueError(
                f"`{command.name}` has no configuration file attached to it"
            )
        path = command.cachedir / config
        if command.changed(KW_CONF) or not path.is_file():
            self.__write_config(path)
        return path
