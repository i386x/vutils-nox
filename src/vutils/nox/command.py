#
# File:    ./src/vutils/nox/command.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-02 21:11:50 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Definitions of commands."""

import contextlib
import functools
import optparse
import os
from collections.abc import Callable, Iterable, MutableMapping, MutableSequence
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Generator,
    Literal,
    TypeGuard,
    Unpack,
    overload,
)

from nox._decorators import Func
from nox.registry import get
from nox.sessions import Session
from setuptools import find_namespace_packages, find_packages

from vutils.nox.pkgspec import InstallMode
from vutils.nox.project import get_where, load_pyproject
from vutils.nox.state import (
    KW_CONF,
    KW_DEPS,
    CommandState,
    Configuration,
    Dependencies,
)
from vutils.nox.utils import identical

if TYPE_CHECKING:
    from vutils.nox import (
        ActionType,
        CommandArgs,
        CommandDefs,
        CommandOptions,
        CommandProps,
        ConfType,
        DepsType,
        StrPath,
    )

#: Parameters, keys, and properties
KW_ACTIONS: Literal["actions"] = "actions"
KW_CACHEDIR: Literal["cachedir"] = "cachedir"
KW_CONFIG: Literal["config"] = "config"
KW_DESCRIPTION: Literal["description"] = "description"
KW_ENVNAME: Literal["envname"] = "envname"
KW_INSTALL_MODE: Literal["install_mode"] = "install_mode"
KW_NAME: Literal["name"] = "name"
KW_PACKAGE: Literal["package"] = "package"
KW_STATEFILE: Literal["statefile"] = "statefile"


def is_action_callable(action: "ActionType | str") -> TypeGuard["ActionType"]:
    """
    Check whether the action is callable.

    :param action: The action
    :return: :obj:`True` if the action is callable
    """
    return callable(action)


def normalize_actions(
    actions: Iterable["ActionType | str"],
) -> Generator["ActionType", None, None]:
    """
    Normalize actions.

    :param actions: The list of actions or their names (can be intermixed)
    :return: the generator yielding actions that are only callables
    :raises KeyError: if an action is a name and that name is not present in
        the Nox registry
    :raises TypeError: if the action taken from the Nox registry is not an
        instance of :class:`.Command`

    If an action is a callable it is yielded as it is. Otherwise, it is looked
    up in the Nox registry and the found callable is then yielded.
    """
    registry = get()

    for action in actions:
        if is_action_callable(action):
            yield action
        if action not in registry:
            raise KeyError(f"`{action}` is not in Nox registry")
        command = registry[action]
        if isinstance(command, Func):
            command = command.func
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


@functools.cache
def find_package() -> str | None:
    """
    Find an importable package in the project directory.

    :return: the importable package name or :obj:`None` if such a package
        cannot be found
    """
    where = get_where(load_pyproject())
    if where is not None:
        where = list(filter(None, where))
    if not where:
        return None
    packages = find_packages(where=where[-1])
    if not packages:
        packages = find_namespace_packages(where=where[-1])
    if not packages:
        return None
    return packages[-1]


class CommandOptsParser(optparse.OptionParser):
    """Command options parser."""

    __slots__ = ()

    def __init__(self, command: "Command") -> None:
        """
        Initialize the parser.

        :param command: The command owning this parser
        """
        optparse.OptionParser.__init__(
            self, prog=command.name, description=command.description
        )
        self.set_defaults(**{KW_INSTALL_MODE: None})
        self.add_option(
            "-U",
            "--upgrade",
            action="store_const",
            dest=KW_INSTALL_MODE,
            const=InstallMode.UPDATE,
            help="upgrade dependencies",
        )
        self.add_option(
            "-f",
            "--force",
            action="store_const",
            dest=KW_INSTALL_MODE,
            const=InstallMode.FORCE,
            help="reinstall dependencies",
        )
        self.add_option(
            "--noinstall",
            action="store_const",
            dest=KW_INSTALL_MODE,
            const=InstallMode.NOINSTALL,
            help="do not install dependencies if they are already installed",
        )

    def process_args(
        self, container: "CommandProps", args: MutableSequence[str]
    ) -> None:
        """
        Parse, process, and store arguments.

        :param container: The container to which parsed and processed arguments
            are going to be stored
        :param args: Arguments to be parsed and processed

        After arguments are parsed, remove ``--upgrade`` and ``--force`` from
        :xarg:`args`, since all dependencies from subcommands are installed at
        the parent level, but keep ``--noinstall`` so it can be propagated into
        subcommands. When :xarg:`args` contain ``--help``, print the help
        screen for the associated command and exit.
        """
        opts, rest = self.parse_args(args)
        del args[: len(args) - len(rest)]
        mode = getattr(opts, KW_INSTALL_MODE, None)
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
    features not included in ordinary Nox sessions. With this class, a user
    can:

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
    DEFS: ClassVar["CommandDefs"] = {KW_DEPS: {}, KW_CONF: {}}

    #: Actions to be executed when the command runs
    __actions: MutableSequence["ActionType"]
    #: The command dependencies container
    __dependencies: Dependencies
    #: The command configuration container
    __configuration: Configuration
    #: The command properties
    __properties: "CommandProps"
    #: The option parser
    __parser: CommandOptsParser
    #: The command state
    __state: CommandState

    __slots__ = (
        "__actions",
        "__dependencies",
        "__configuration",
        "__properties",
        "__parser",
        "__state",
    )

    def __collect_actions(self, kwargs: "CommandArgs") -> None:
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
    def __collect_defs(cls, kind: Literal["deps"]) -> "DepsType": ...

    @overload
    @classmethod
    def __collect_defs(cls, kind: Literal["conf"]) -> "ConfType": ...

    @classmethod
    def __collect_defs(cls, kind: str) -> "DepsType | ConfType":
        """
        Collect a definition based on :xarg:`kind`.

        :param kind: The kind of definition being collected (either ``deps``
            for dependencies definition or ``conf`` for configuration
            definition)
        :return: the collected definition
        """
        container: MutableMapping[str, object] = {}
        bases = list(cls.__mro__)
        while bases:
            base = bases.pop()
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

        deps = type(self).__collect_defs(KW_DEPS)
        for pkg, spec in deps.items():
            self.__dependencies.add(pkg, spec)
        self.__dependencies.commit()

    def __initialize_configuration(self) -> None:
        """Initialize configuration."""
        self.__configuration = Configuration()

        conf = type(self).__collect_defs(KW_CONF)
        for key, value in conf.items():
            self.__configuration.add(key, value)
        self.__configuration.commit()

    def __collect_properties(self, props: "CommandProps") -> None:
        """
        Collect properties from :xarg:`props`.

        :param props: Properties
        """
        if len(self.__actions) == 1 and not identical(
            self.__actions[0], self.run
        ):
            name = self.__actions[0].__name__
            desc = (
                self.__actions[0].description
                if isinstance(self.__actions[0], Command)
                else self.__actions[0].__doc__
            )
        else:
            name = type(self).__name__.lower()
            desc = type(self).__doc__
        props.setdefault(KW_NAME, name)
        props.setdefault(KW_DESCRIPTION, desc)
        props[KW_DESCRIPTION] = normalize_description(props[KW_DESCRIPTION])
        props.setdefault(KW_ENVNAME, name)
        package = find_package()
        if package is not None:
            props.setdefault(KW_PACKAGE, package)
        props.setdefault(KW_CONFIG, None)
        props.setdefault(KW_INSTALL_MODE, InstallMode.NOINSTALL)
        self.__properties = props

    def __initialize_state(self, statefile: str) -> None:
        """
        Create the command state and propagate it to subcommands.

        :param statefile: The name of the command state storage

        This method must be called after the all subcommands are gathered.
        """
        self.set_state(CommandState(statefile))

        def callback(cmd: Command) -> None:
            """
            Assign the command state to the subcommand.

            :param cmd: The subcommand
            """
            cmd.set_state(self.__state)

        self.traverse(callback)

    def __init__(self, **kwargs: Unpack["CommandArgs"]) -> None:
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
          :meth:`.Command.run` is used
        * ``name``, specifying the name of the session; if not given and there
          is a single action attached to this command and it is not
          :meth:`.Command.run`, the name is the name of this action; otherwise,
          the name is the ``__name__`` of this command in lowercase
        * ``description``, specifying the session description; if not given and
          there is a single action attached to this command and it is not
          :meth:`.Command.run`, the description is read from the ``__doc__``
          (or ``description`` if the action is a :class:`.Command` instance)
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
        * ``cachedir``, specifying the shared cache directory; if not given
          the :class:`nox.sessions.Session`'s shared cache directory is used
          (set when this command is executed)
        * ``config``, specifying the name of a configuration file where the
          configuration defined for this command via the
          :deco:`~vutils.nox.decorators.cfg` decorator is stored; if not given
          the configuration file is not accessible
        * ``install_mode``, specifying a mode of how and when dependencies are
          installed: (1) :attr:`InstallMode.NOINSTALL
          <vutils.nox.pkgspec.InstallMode.NOINSTALL>` means do not install
          dependencies if they are already installed; (2)
          :attr:`InstallMode.UPDATE
          <vutils.nox.pkgspec.InstallMode.UPDATE>` means update dependencies;
          :attr:`InstallMode.FORCE <vutils.nox.pkgspec.InstallMode.FORCE>`
          means reinstall dependencies; if not specified then
          :attr:`InstallMode.NOINSTALL
          <vutils.nox.pkgspec.InstallMode.NOINSTALL>` is used; this key-value
          argument can be overridden from the command line via positional
          arguments passed to any :class:`.Command`-based session (type ``nox
          -s dummy -- --help`` for more info)
        * ``statefile``, specifying the name of a file where the command state
          is stored; if not given then ``".state-{envname}"`` is used
        """
        self.__collect_actions(kwargs)
        self.__initialize_dependencies()
        self.__initialize_configuration()
        self.__collect_properties(kwargs)
        self.__parser = CommandOptsParser(self)
        self.__initialize_state(
            kwargs.pop(KW_STATEFILE, f".state-{self.envname}")
        )

    def traverse(
        self, callback: Callable[["Command"], None], shallow: bool = False
    ) -> None:
        """
        Traverse subcommands in the first order manner.

        :param callback: The callback applied on every subcommand
        :param shallow: When set to :obj:`True`, do not traverse subcommands'
            children
        """
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

    def set_state(self, state: CommandState) -> None:
        """
        Set the command state.

        :param state: The command state
        """
        self.__state = state

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
    def cachedir(self) -> os.PathLike[str]:
        """
        Get the shared cache directory.

        :return: the shared cache directory
        :raises KeyError: when this property has been read too early
        """
        if KW_CACHEDIR not in self.__properties:
            detail = (
                f"{self.name}: `chachedir` property has not been set yet"
                " (probably accessed before the command has been invoked)"
            )
            raise KeyError(detail)
        return self.__properties[KW_CACHEDIR]

    @property
    def opts(self) -> "CommandOptions":
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

    def config(self, fname: str | None = None) -> "StrPath | None":
        """
        Prepare and get the configuration file for this command.

        :param fname: The name of the requested configuration file
        :return: the path to the requested configuration file
        """
        if fname is None:
            return self.__properties[KW_CONFIG]
        self.__properties[KW_CONFIG] = fname
        return self.__configuration.config(self)

    def run(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Run the command body.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not

        Users can override this method to perform their specific commands. By
        default this method is no-op.
        """

    @contextlib.contextmanager
    def context(
        self, session: Session, is_subcommand: bool
    ) -> Generator[None, None, None]:
        """
        Create a context for running commands.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not
        :return: the generator object

        Save the old cache directory and installation mode. If this command is
        not a subcommand, load the command state from the persistent storage.
        If the cache directory is not set, use the one provided by
        :xarg:`session`. Set the installation mode based on command line
        arguments passed to this command. After the command and its subcommands
        are finished, restore the previous state and store the command state to
        the persistent storage in case this command is not a subcommand.
        """
        cachedir = self.__properties.get(KW_CACHEDIR, None)
        install_mode = self.__properties[KW_INSTALL_MODE]

        try:
            if not is_subcommand:
                self.__state.load(session)
            if cachedir is None:
                self.__properties[KW_CACHEDIR] = session.cache_dir
            self.__parser.process_args(self.__properties, session.posargs)
            yield
        finally:
            self.__properties[KW_INSTALL_MODE] = install_mode
            if cachedir is None:
                del self.__properties[KW_CACHEDIR]
            if not is_subcommand:
                self.__state.store(session)

    def __call__(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Run the command.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not

        Install dependencies and then run the specified actions. If no actions
        were given during the command initialization, execute
        :meth:`.Command.run`.

        Note that dependencies are not installed if this command is a
        subcommand of some other command, since all dependencies were gathered
        and installed on the top of the command tree.
        """
        with self.context(session, is_subcommand):
            if not is_subcommand:
                self.__dependencies.install(
                    session, self, mode=self.opts[KW_INSTALL_MODE]
                )

            for action in self.__actions:
                action(session, True)
