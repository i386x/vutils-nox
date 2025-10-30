#
# File:    ./src/vutils/nox/command.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-02 21:11:50 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Definitions of commands."""

import hashlib

from collections.abc import MutableMapping
from typing import TYPE_CHECKING, overload

from pydantic import BaseModel, ConfigDict

from vutils.nox.pkgspec import LocalDist, Security
from vutils.nox.utils import data2str

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, MutableSequence
    from hashlib import HASH as Hasher
    from io import TextIOWrapper
    from os import PathLike
    from typing import ClassVar, Generator, Literal, TypeVar, Unpack

    from nox.sessions import Session

    from vuitls.nox import (
        ActionType,
        CommandArgs,
        CommandBaseType,
        CommandDefs,
        CommandProps,
        ConfType,
        DepsType,
        PkgSpecType,
    )

    T = TypeVar("T", bound=Security|str)

#: Parameters, keys, and properties
KW_ACTIONS: Literal["actions"] = "actions"
KW_CONF: Literal["conf"] = "conf"
KW_DEPS: Literal["deps"] = "deps"
KW_DESCRIPTION: Literal["description"] = "description"
KW_MODULE: Literal["module"] = "module"
KW_NAME: Literal["name"] = "name"


class CommandStateData(BaseModel):
    """The :class:`~.CommandState` data model."""

    model_config = ConfigDict(str_min_length=1)

    dependencies: MutableMapping[str, MutableMapping[str, str]]
    configuration: MutableMapping[str, str]


class CommandState:
    """Persistent command state shared between runs."""

    #: The name of the file that serves as the persistent storage
    __name: str
    #: The path to the persistent storage
    __storage: PathLike[str] | None
    #: The data reflecting the command state
    __data: CommandStateData

    __slots__ = ("__name", "__storage", "__data")

    def __init__(self, name: str = ".state") -> None:
        """
        Initialize the command state.

        :param name: The name of the persistent storage
        """
        self.__name = name
        self.__storage = None
        self.__data = CommandStateData(dependencies={}, configuration={})

    def __get_storage(self, session: Session) -> PathLike[str]:
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
        :raises pydantic.ValidationError: if the persistent storage is
            corrupted

        By calling this method changes made so far are discarded and replaced
        with the recent data from the persistent storage.
        """
        storage: PathLike[str] = self.__get_storage(session)
        if not storage.is_file():
            return
        fobj: TextIOWrapper
        with storage.open() as fobj:
            self.__data = CommandStateData.model_validate_json(
                fobj.read(), strict=True
            )

    def store(self, session: Session) -> None:
        """
        Store the data to the persistent storage.

        :param session: The Nox session
        :raises pydantic.PydanticSerializationError: if the data are corrupted
        """
        storage: PathLike[str] = self.__get_storage(session)
        with storage.open("w") as fobj:
            fobj.write(self.__data.model_dump_json(warnings="error"))

    def changed_deps(self, session: Session, command: Command) -> bool:
        """
        Check whether the set of packages to install has been changed.

        :param session: The Nox session
        :param command: The command
        :return: :obj:`True` if the set of packages associated with
            :xarg:`command` has been changed
        """
        cmd2envs: MutableMapping[str, MutableMapping[str, str]] = (
            self.__data.dependencies
        )
        changed: bool = command.name not in cmd2envs
        env2sum: MutableMapping[str, str] = cmd2envs.setdefault(
            command.name, {}
        )
        new_checksum: str = command.checksum(KW_DEPS)
        changed = changed or command.envname not in env2sum
        checksum: str = env2sum.setdefault(command.envname, new_checksum)
        session.log(
            "DEPENDENCIES: %s: %s: %s (%s)",
            command.name,
            command.envname,
            new_checksum,
            "added" if changed else (
                f"changed from {checksum}"
                if new_checksum != checksum
                else "unchanged"
            ),
        )
        if new_checksum != checksum:
            env2sum[command.envname] = new_checksum
            return True
        return changed

    def changed_conf(self, session: Session, command: Command) -> bool:
        """
        Check whether the configuration has been changed.

        :param session: The Nox session
        :param command: The command
        :return: :obj:`True` if the configuration associated with
            :xarg:`command` has been changed
        """
        if command.config() is None:
            return False
        config: str = command.config()
        cfg2sum: MutableMapping[str, str] = self.__data.configuration
        new_checksum: str = command.checksum(KW_CONF)
        changed: bool = config not in cfg2sum
        checksum: str = cfg2sum.setdefault(config, new_checksum)
        session.log(
            "CONFIGURATION: %s: %s (%s)",
            config,
            new_checksum,
            "added" if changed else (
                f"changed from {checksum}"
                if new_checksum != checksum
                else "unchanged"
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

    def items(self) -> Generator[str]:
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
            hasher: Hasher = hashlib.new("sha512")

            item: str
            for item in self.items():
                hasher.update(item.encode())
            self.__checksum = hasher.hexdigest()
        return self.__checksum


def add_deps_to(
    container: Dependencies, deps: Mapping[str, Iterable[T]], kind: T
) -> None:
    """
    Add dependencies to the container.

    :param container: The container to store dependencies in
    :param deps: Dependencies
    :param kind: The dummy dependency from which the dependency type is derived
        in case :xarg:`deps` contains an item with the empty list of specifiers
        (this is needed to distinct between an update and ordinary dependency)
    """
    pkg: str
    specs: Iterable[T]
    for pkg, specs in deps:
        spec: T
        for spec in specs:
            container.add(pkg, spec)
        else:
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

    def add(self, name: str, item: PkgSpecType) -> None:
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
            detail: str = (
                "The `.` package name is reserved for locally distributed"
                " packages only"
            )
            raise ValueError(detail)
        if isinstance(item, Security):
            self.__updates.setdefault(pkg, [])
            if str(item):
                self.__updates[name].append(item)
        elif isinstance(item, str):
            item = item.strip()
            self.__main.setdefault(name, [])
            if item:
                self.__main[name].append(item)
        elif isinstance(item, LocalDist):
            if name != ".":
                detail: str = (
                    "Locally distributed packages should be named `.` ("
                    f"`{name}` given)"
                )
                raise ValueError(detail)
            if self.__local is None or self.__local <= item:
                self.__local = item

    def add_myself_to(self, container: Dependencies) -> None:
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

        depset: Mapping[str, Iterable[Security | str]]
        for depset in (self.__updates, self.__main):
            pkg: str
            specs: Iterable[Security | str]
            for pkg, specs in depset:
                if specs:
                    self.__install_args.extend(
                        [f"{pkg} {spec}" for spec in specs]
                    )
                else:
                    self.__install_args.append(pkg)
        Container.commit(self)

    def items(self) -> Generator[str]:
        """
        Yield install arguments.

        :return: the generator yielding install arguments

        The checksum of the dependencies container is computed from the
        arguments passed to the Python package installer.
        """
        item: str
        for item in self.__install_args:
            yield item

    def install(
        self, session: Session, command: Command, force: bool = False
    ) -> None:
        """
        Install dependencies held by this container.

        :param session: The Nox session
        :param command: The command owning this container
        :param force: :obj:`True` when force re-installation of all
            dependencies is requested
        """
        if self.__local:
            self.__local.install(session, force_reinstall=force)
        if command.changed(KW_DEPS, session) or force:
            session.install(*self.__install_args, silent=False)


class RemoveMarker:
    """
    Configuration item remove marker.

    A configuration item marked with this marker will be removed (not included)
    in the final configuration.
    """


class Configuration(Container):
    """Configuration container."""

    #: The configuration data
    __data: ConfType

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
        self.__data[name] = item

    def items(self) -> Generator[str]:
        """"""
        yield from data2str(self.__data)


class Command:
    """
    Bring Nox user experience closer to Tox.

    The base class for user defined Nox commands/sessions, providing several
    features not included in ordinary Nox sessions. With this class users can:

    * specify the list of command dependencies that will be automatically
      installed
    * specify the name of Python virtual environment under which the command
      will be executed
    * create a new command by command composition; a subcommand dependencies
      will be added to the new command dependencies
    * specify a configuration for the command that will be stored to the file
      and passed to the given tool
    """

    DEFS: ClassVar[CommandDefs] = {KW_DEPS: {}, KW_CONF: {}}

    __state: CommandState
    __actions: MutableSequence[ActionType]
    __dependencies: Dependencies
    __configuration: Configuration
    __properties: CommandProps

    __slots__ = (
        "__state",
        "__actions",
        "__dependencies",
        "__configuration",
        "__properties",
    )

    def __collect_actions(self, kwargs: CommandArgs) -> None:
        """
        Collect actions from :xarg:`kwargs`.

        :param kwargs: Key-value arguments
        """
        self.__actions = []
        self.__actions.extend(kwargs.pop(KW_ACTIONS, []))
        if len(self.__actions) == 0:
            self.__actions.append(self.run)

    @overload
    @classmethod
    def __collect_defs(cls, kind: Literal["deps"]) -> DepsType: ...

    @overload
    @classmethod
    def __collect_defs(cls, kind: Literal["conf"]) -> ConfType: ...

    @classmethod
    def __collect_defs(cls, kind: str) -> DepsType | ConfType:
        """
        Collect a definition based on :xarg:`kind`.

        :param kind: The kind of definition being collected (either ``deps``
            for dependencies definition or ``conf`` for configuration
            definition)
        :return: the collected definition
        """
        container: MutableMapping[str, object] = {}
        bases: MutableSequence[CommandBaseType] = list(cls.__mro__)
        while bases:
            base: CommandBaseType = bases.pop(-1)
            if issubclass(base, Command):
                container.update(base.DEFS[kind])
        return container

    def __initialize_dependencies(self) -> None:
        """Initialize dependencies."""
        self.__dependencies = Dependencies()

        action: ActionType
        for action in self.__actions:
            if isinstance(action, Command):
                action.add_deps_to(self.__dependencies)
        pkg: str
        spec: PkgSpecType
        for pkg, spec in type(self).__collect_defs(KW_DEPS):
            self.__dependencies.add(pkg, spec)
        self.__dependencies.commit()

    def __initialize_configuration(self) -> None:
        """Initialize configuration."""
        self.__configuration = Configuration()

        key: str
        value: object
        for key, value in type(self).__collect_defs(KW_CONF):
            if value is RemoveMarker:
                continue
            self.__configuration.add(pkg, value)
        self.__configuration.commit()

    def __collect_properties(self, props: CommandProps) -> None:
        """
        Collect properties from :xarg:`props`.

        :param props: Properties
        """
        name: str
        desc: str
        if len(self.__actions) == 1 and self.__actions[0] is not self.run:
            name = self.__actions[0].__name__
            desc = self.__actions[0].__doc__
        else:
            name = type(self).__name__.lower()
            desc = type(self).__doc__
        props.setdefault(KW_NAME, name)
        props.setdefault(KW_DESCRIPTION, desc)
        self.__properties = props

    def __init__(
        self, state: CommandState, **kwargs: Unpack(CommandArgs)
    ) -> None:
        """"""
        self.__state = state
        self.__collect_actions(kwargs)
        self.__initialize_dependencies()
        self.__initialize_configuration()
        self.__collect_properties(kwargs)

    @property
    def __name__(self):
        """"""
        return self.name

    @property
    def __doc__(self):
        """"""
        return self.description

    def run(self, session):
        """"""

    def __call__(self, session):
        """"""
        self.install(session)
        for command in self.callables:
            command(session)
