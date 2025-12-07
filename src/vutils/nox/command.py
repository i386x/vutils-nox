#
# File:    ./src/vutils/nox/command.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-02 21:11:50 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Definitions of commands."""

from collections.abc import MutableMapping
import configparser
import contextlib
import hashlib
import optparse
import pathlib
from typing import TYPE_CHECKING, overload

from nox.logger import logger
from pydantic import BaseModel, ConfigDict
from setuptools import find_namespace_packages, find_packages
from tomli_w import dump as toml_dump

from vutils.nox.pkgspec import InstallMode, LocalDist, Security
from vutils.nox.utils import data2str, normalize_actions, normalize_description

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, MutableSequence
    import io
    import os
    from typing import ClassVar, Generator, Literal, TypeVar, Unpack

    from nox.sessions import Session

    from vuitls.nox import (
        ActionType,
        CommandArgs,
        CommandBaseType,
        CommandDefs,
        CommandOptions,
        CommandProps,
        ConfType,
        DepsType,
        PkgSpecType,
        StrPath,
    )

    T = TypeVar("T", bound=Security|str)

#: Parameters, keys, and properties
KW_ACTIONS: Literal["actions"] = "actions"
KW_CACHEDIR: Literal["cachedir"] = "cachedir"
KW_CONF: Literal["conf"] = "conf"
KW_CONFIG: Literal["config"] = "config"
KW_DEPS: Literal["deps"] = "deps"
KW_DESCRIPTION: Literal["description"] = "description"
KW_ENVNAME: Literal["envname"] = "envname"
KW_INSTALL_MODE: Literal["install_mode"] = "install_mode"
KW_NAME: Literal["name"] = "name"
KW_PACKAGE: Literal["package"] = "package"
KW_ROOTDIR: Literal["rootdir"] = "rootdir"
KW_STATEFILE: Literal["statefile"] = "statefile"


class CommandStateData(BaseModel):
    """The :class:`~.CommandState` data model."""

    model_config = ConfigDict(str_min_length=1)

    # Command name to checksum mappings
    dependencies: MutableMapping[str, str]
    configuration: MutableMapping[str, str]


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
        :raises pydantic.ValidationError: if the persistent storage is
            corrupted

        By calling this method changes made so far are discarded and replaced
        with the recent data from the persistent storage.
        """
        storage: os.PathLike[str] = self.__get_storage(session)
        if not storage.is_file():
            return
        fobj: io.TextIOWrapper
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
        storage: os.PathLike[str] = self.__get_storage(session)

        fobj: io.TextIOWrapper
        with storage.open("w") as fobj:
            fobj.write(self.__data.model_dump_json(warnings="error"))

    def changed_deps(self, command: Command) -> bool:
        """
        Check whether the set of packages to install has been changed.

        :param command: The command
        :return: :obj:`True` if the set of packages associated with
            :xarg:`command` has been changed
        """

        def callback(cmd: Command) -> None:
            """
            Gather the state of :xarg:`cmd`'s dependencies.

            :param cmd: The command
            """
            cmd.changed(KW_DEPS)

        # Gather the state of subcommands' dependencies ...
        command.traverse(callback)
        # ... and then of command's ones
        cmd2sum: MutableMapping[str, str] = self.__data.dependencies
        new_checksum: str = command.checksum(KW_DEPS)
        changed: bool = command.name not in cmd2sum
        checksum: str = cmd2sum.setdefault(command.name, new_checksum)
        logger.log(
            "DEPENDENCIES: %s: %s (%s)",
            command.name,
            new_checksum,
            "added" if changed else (
                f"changed from {checksum}"
                if new_checksum != checksum
                else "unchanged"
            ),
        )
        if new_checksum != checksum:
            cmd2sum[command.name] = new_checksum
            return True
        return changed

    def changed_conf(self, command: Command) -> bool:
        """
        Check whether the configuration has been changed.

        :param command: The command
        :return: :obj:`True` if the configuration associated with
            :xarg:`command` has been changed
        """
        config: str | None = command.config()
        if config is None:
            return False
        cfg2sum: MutableMapping[str, str] = self.__data.configuration
        new_checksum: str = command.checksum(KW_CONF)
        changed: bool = config not in cfg2sum
        checksum: str = cfg2sum.setdefault(config, new_checksum)
        logger.log(
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
            hasher: hashlib.HASH = hashlib.new("sha512")

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
        self,
        session: Session,
        command: Command,
        mode: InstallMode = InstallMode.NOINSTALL,
    ) -> None:
        """
        Install dependencies held by this container.

        :param session: The Nox session
        :param command: The command owning this container
        :param mode: The installation mode
        """
        if self.__local:
            self.__local.install(session, mode=mode)
        if command.changed(KW_DEPS) or mode > InstallMode.NOINSTALL:
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
            suffix of the configuration file, is not supported
        """
        fobj: io.TextIOWrapper

        suffix: str = path.suffix
        if suffix == ".toml":
            with path.open("wb") as fobj:
                toml_dump(self.__data, fobj)
        elif suffix in (".cfg", ".ini"):
            parser: configparser.ConfigParser = configparser.ConfigParser()
            parser.read_dict(self.__data)
            with path.open("w") as fobj:
                parser.write(fobj)
        else:
            raise ValueError(f"{path.name}: Format is not supported")

    def config(self, command: Command) -> os.PathLike[str]:
        """
        Prepare and get the configuration file for the command.

        :param command: The command
        :return: the path to the configuration file
        :raises ValueError: when the name of the configuration file cannot be
            retrieved from the command
        """
        config: StrPath | None = command.config()
        if config is None:
            raise ValueError(
                f"`{command.name}` has no configuration file attached to it"
            )
        path: os.PathLike[str] = command.cachedir / config
        if command.changed(KW_CONF) or not path.is_file():
            self.__write_config(path)
        return path


class CommandOptsParser(optparse.OptionParser):
    """Command options parser."""

    __slots__ = ()

    def __init__(self, command: Command) -> None:
        """
        Initialize the parser.

        :param command: The command owning this parser
        """
        optparse.OptionParser.__init__(
            self, prog=command.name, description=command.description
        )
        self.set_defaults(*{KW_INSTALL_MODE: None})
        self.add_option(
            "-r",
            "--reinstall",
            action="store_const",
            dest=KW_INSTALL_MODE,
            const=InstallMode.REINSTALL,
            help="reinstall dependencies",
        )
        self.add_option(
            "-f",
            "--force",
            action="store_const",
            dest=KW_INSTALL_MODE,
            const=InstallMode.FORCE,
            help="force reinstall dependencies",
        )
        self.add_option(
            "--noinstall",
            action="store_const",
            dest=KW_INSTALL_MODE,
            const=InstallMode.NOINSTALL,
            help="do not install dependencies if they are already installed",
        )

    def process_args(
        self, container: CommandProps, args: MutableSequence[str]
    ) -> None:
        """
        Parse, process, and store arguments.

        :param container: The container to which parsed and processed arguments
            are going to be stored
        :param args: Arguments to be parsed and processed
        :raises optparse.OptParseError: when an error occurs during argument
            parsing and/or processing

        After arguments are parsed, remove ``--reinstall`` and ``--force`` from
        :xarg:`args`, since all dependencies from subcommands are installed at
        the parent level, but keep ``--noinstall`` so it can be propagated into
        subcommands. When :xarg:`args` contain ``--help``, print the help
        screen for the associated command and exit.
        """
        opts: optparse.Values
        rest: Iterable[str]
        opts, rest = self.parse_args(args)
        del args[:len(args) - len(rest)]
        mode: InstallMode = getattr(opts, KW_INSTALL_MODE, None)
        if mode == InstallMode.NOINSTALL:
            if args:
                args.insert(0, "--")
            args.insert(0, "--noinstall")
        if mode is not None:
            container[KW_INSTALL_MODE] = mode

    def error(self, msg: str) -> None:
        """
        Issue an error.

        :param msg: The error message
        :raises optparse.OptParseError: with :xarg:`msg` when invoked
        """
        raise optparse.OptParseError(f"{self.get_prog_name()}: {msg}")


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

    #: Command definitions (dependencies and configuration)
    DEFS: ClassVar[CommandDefs] = {KW_DEPS: {}, KW_CONF: {}}

    #: The command state
    __state: CommandState
    #: Actions to be executed when the command runs
    __actions: MutableSequence[ActionType]
    #: The command dependencies container
    __dependencies: Dependencies
    #: The command configuration container
    __configuration: Configuration
    #: The command properties
    __properties: CommandProps
    #: The option parser
    __parser: CommandOptsParser

    __slots__ = (
        "__state",
        "__actions",
        "__dependencies",
        "__configuration",
        "__properties",
        "__parser",
    )

    def __collect_actions(self, kwargs: CommandArgs) -> None:
        """
        Collect actions from :xarg:`kwargs`.

        :param kwargs: Key-value arguments
        """
        self.__actions = []
        self.__actions.extend(normalize_actions(kwargs.pop(KW_ACTIONS, [])))
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
            base: CommandBaseType = bases.pop()
            if issubclass(base, Command):
                container.update(base.DEFS[kind])
        return container

    def __initialize_dependencies(self) -> None:
        """Initialize dependencies."""
        self.__dependencies = Dependencies()

        def callback(cmd: Command) -> None:
            """
            Add command dependencies to the container.

            :param cmd: The command
            """
            cmd.add_deps_to(self.__dependencies)

        self.traverse(callback, shallow=True)

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
        props[KW_DESCRIPTION] = normalize_description(props[KW_DESCRIPTION])
        props.setdefault(KW_ENVNAME, name)
        where: os.PathLike[str] = (
            props.setdefault(KW_ROOTDIR, pathlib.Path.cwd()) / "src"
        )
        packages: Iterable[str] = find_packages(where=where)
        if not packages:
            packages = find_namespace_packages(where=where)
        if packages:
            props.setdefault(KW_PACKAGE, packages[-1])
        props.setdefault(KW_CONFIG, None)
        props.setdefault(KW_INSTALL_MODE, InstallMode.NOINSTALL)
        self.__properties = props

    def __init__(self, **kwargs: Unpack(CommandArgs)) -> None:
        """
        Initialize the command.

        :param kwargs: The command key-value arguments

        Supported key-value arguments are:

        * ``actions``, specifying a list of actions to be executed; an action
          is either a callable object accepting an instance of
          :class:`nox.sessions.Session` as its only argument and returning
          :obj:`None` or the name of a previously registered command via the
          :deco:`~vutils.nox.decorators.add` decorator; actions are executed in
          order they are specified; if no action is given,
          :meth:`~.Command.run` is used
        * ``name``, specifying the name of the session; if not given and there
          is a single action attached to this command and it is not
          :meth:`~.Command.run`, the name is the name of this action;
          otherwise, the name is the ``__name__`` of this command in lowercase
        * ``description``, specifying the session description; if not given and
          there is a single action attached to this command and it is not
          :meth:`~.Command.run`, the description is read from the ``__doc__``
          property of this action; otherwise, the description is read from the
          ``__doc__`` property of this command; if the description is
          multi-line, the first line is taken; the first letter is lowercased
          and the sole last dot, if present, is removed from the description
        * ``envname``, specifying the name of the Python virtual environment;
          if not given it is same as ``name``
        * ``package``, specifying the importable name of the Python package,
          produced via ``python -m build`` and installed via ``pip install -e
          .`` or ``pip install <wheel produced during the build>``, which
          source is under ``./src`` directory, relative to the project root
          directory; if not given it is discovered automatically
        * ``rootdir``, specifying the root directory of the project; if not
          given the current working directory is used
        * ``cachedir``, specifying the shared cache directory; if not given
          the :class:`nox.sessions.Session`'s shared cache directory is used
          (set when this command is executed)
        * ``config``, specifying the name of a configuration file where the
          configuration defined for this command via the
          :deco:`~vutils.nox.decorators.cfg` decorator is stored; if not given
          the configuration file is not accessible
        * ``install_mode``, specifying a mode of how and when dependencies are
          installed: (1) :attr:`~vutils.nox.pkgspec.NOINSTALL` means do not
          install dependencies if they are already installed; (2)
          :attr:`~vutils.nox.pkgspec.REINSTALL` means reinstall dependencies;
          :attr:`~vutils.nox.pkgspec.FORCE` means force reinstall dependencies;
          if not specified then :attr:`~vutils.nox.pkgspec.NOINSTALL` is used;
          this key-value argument can be overridden from the command line via
          positional arguments passed to any :class:`.Command`-based session
          (type ``nox -s dummy -- --help`` for more info)
        * ``statefile``, specifying the name of a file where the command state
          is stored; if not given then ``".state"`` is used
        """
        self.__state = CommandState(kwargs.pop(KW_STATEFILE, ".state"))
        self.__collect_actions(kwargs)
        self.__initialize_dependencies()
        self.__initialize_configuration()
        self.__collect_properties(kwargs)
        self.__parser = CommandOptsParser(self)

    def traverse(
        self, callback: Callable[[Command], None], shallow: bool = False
    ) -> None:
        """
        Traverse subcommands in the first order manner.

        :param callback: The callback applied on every subcommand
        :param shallow: When set to :obj:`True`, do not traverse subcommands'
            children
        """
        subcommand: ActionType
        for subcommand in self.__actions:
            if isinstance(subcommand, Command):
                callback(subcommand)
                if not shallow:
                    subcommand.traverse(callback)

    def add_deps_to(self, container: Dependencies) -> None:
        """
        Add dependencies from this command to :xarg:`container`.

        :param container: The container to which these command's dependencies
            are going to be stored
        """
        self.__dependencies.add_myself_to(container)

    @property
    def __name__(self) -> str:
        """
        Get the command name.

        :return: the command name
        """
        return self.name

    @property
    def name(self) -> str:
        """
        Get the command name.

        :return: the command name
        """
        return self.__properties[KW_NAME]

    @property
    def __doc__(self) -> str:
        """
        Get the command description.

        :return: the command description
        """
        return self.description

    @property
    def description(self) -> str:
        """
        Get the command description.

        :return: the command description
        """
        return self.__properties[KW_DESCRIPTION]

    @property
    def envname(self) -> str:
        """
        Get the name of the Python environment.

        :return: the name of the Python environment under which this command is
            running
        """
        return self.__properties[KW_ENVNAME]

    @property
    def package(self) -> str:
        """
        Get the importable package name.

        :return: the name of the Python package discovered by Setuptools from
            the project's ``./src`` directory in format consumable by Python
            import mechanism
        :raises KeyError: when the discovery has failed
        """
        if KW_PACKAGE not in self.__properties:
            raise KeyError(
                f"{self.name}.package: Package discovery has failed"
            )
        return self.__properties[KW_PACKAGE]

    @property
    def rootdir(self) -> os.PathLike[str]:
        """
        Get the project root directory.

        :return: the project root directory
        """
        return self.__properties[KW_ROOTDIR]

    @property
    def cachedir(self) -> os.PathLike[str]:
        """
        Get the shared cache directory.

        :return: the shared cache directory
        :raises KeyError: when this property has been read too early
        """
        if KW_CACHEDIR not in self.__properties:
            detail: str = (
                f"{self.name}: `chachedir` property has not been yet set"
                " (probably accessed before the command has been invoked)"
            )
            raise KeyError(detail)
        return self.__properties[KW_CACHEDIR]

    @properties
    def opts(self) -> CommandOptions:
        """
        Get the command options.

        :return: the command options
        """
        return {KW_INSTALL_MODE: self.__properties[KW_INSTALL_MODE]}

    def changed(self, what: Literal["deps", "conf"]) -> bool:
        """
        Test whether the selected container has been changed.

        :param what: The container selector (either ``deps`` for dependencies
            or ``conf`` for configuration)
        :return: :obj:`True` whether the selected container has been changed
        """
        return (
            self.__state.changed_deps(self)
            if what == KW_DEPS
            else self.__state.changed_conf(self)
        )

    def checksum(self, what: Literal["deps", "conf"]) -> str:
        """
        Return the checksum of the selected container.

        :param what: The container selector (either ``deps`` for dependencies
            or ``conf`` for configuration)
        :return: the checksum of the selected container
        """
        return (
            self.__dependencies.checksum()
            if what == KW_DEPS
            else self.__configuration.checksum()
        )

    def config(self, fname: str | None = None) -> StrPath | None:
        """
        Prepare and get the configuration file for this command.

        :param fname: The name of the requested configuration file
        :return: the path to the requested configuration file
        """
        if fname is None:
            return self.__properties[KW_CONFIG]
        self.__properties[KW_CONFIG] = fname
        return self.__configuration.config(self)

    def run(self, session: Session, state: CommandState | None = None) -> None:
        """
        Run the command body.

        :param session: The Nox session
        :param state: The command state

        Users can override this method to perform their specific commands. By
        default this method is no-op. If :xarg:`state` is not :obj:`None`, this
        means that this command is a subcommand of some other command.
        """

    @contextlib.contextmanager
    def context(
        self, session: Session, state: CommandState | None = None
    ) -> Generator[None]:
        """
        Create a context for running commands.

        :param session: The Nox session
        :param state: The command state

        Save the old command state, cache directory, and installation mode. If
        :xarg:`state` is not :obj:`None`, set the command state to
        :xarg:`state`. Otherwise, load the command state from the persistent
        storage. If the cache directory is not set, use the one provided by
        :xarg:`session`. Set the installation mode based on command line
        arguments passed to this command. After the command and its subcommands
        are finished, restore previous state. If :xarg:`state` is :obj:`None`,
        store the command state to the persistent storage.
        """
        old_state: CommandState = self.__state
        cachedir: os.PathLike[str] | None = self.__properties.get(
            KW_CACHEDIR, None
        )
        install_mode: InstallMode = self.__properties[KW_INSTALL_MODE]

        try:
            if state is not None:
                self.__state = state
            else:
                self.__state.load(session)
            if cachedir is None:
                self.__properties[KW_CACHEDIR] = session.cache_dir
            self.__parser.process_args(self.__properties, session.posargs)
            yield
        finally:
            self.__properties[KW_INSTALL_MODE] = install_mode
            if cachedir is None:
                del self.__properties[KW_CACHEDIR]
            if state is not None:
                self.__state = old_state
            else:
                self.__state.store(session)

    def __call__(
        self, session: Session, state: CommandState | None = None
    ) -> None:
        """
        Run the command.

        :param session: The Nox session
        :param state: The command state

        Install dependencies and then run the specified actions. If no actions
        were given during the command initialization, execute
        :meth:`~.Command.run`.

        Note that dependencies are not installed if this command is a
        subcommand (this is indicated by :xarg:`state` not being :obj:`None`)
        of some other command, since all dependencies were gathered and
        installed on the top of the command tree.
        """
        with self.context(session, state):
            if state is None:
                self.__dependencies.install(
                    session, self, mode=self.opts[KW_INSTALL_MODE]
                )

            action: ActionType
            for action in self.__actions:
                action(session, self.__state)
