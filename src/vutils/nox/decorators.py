#
# File:    ./src/vutils/nox/decorators.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-11-03 01:58:18 +0100
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Decorators."""

from collections.abc import Iterable
from typing import (
    TYPE_CHECKING,
    Generator,
    Literal,
    TypeGuard,
    TypeVar,
    Unpack,
)

from nox.registry import session_decorator

from vutils.nox.command import (
    KW_ACTIONS,
    KW_CACHEDIR,
    KW_CONF,
    KW_CONFIG,
    KW_DEPS,
    KW_DESCRIPTION,
    KW_ENVNAME,
    KW_INSTALL_MODE,
    KW_NAME,
    KW_PACKAGE,
    KW_STATEFILE,
    Command,
)
from vutils.nox.pkgspec import DistKind, LocalDist, Security
from vutils.nox.project import project_dependencies
from vutils.nox.utils import DIST_DIR_NAME, KW_PYTHON, container_at_path

if TYPE_CHECKING:
    from vutils.nox import (
        AddArgs,
        CommandArgs,
        CommandArgsKey,
        CommandArgsOnlyKey,
        CommandDecoratorType,
        CommonArgsKey,
        MatrixArgs,
        SessionArgs,
        SessionArgsKey,
        SessionArgsOnlyKey,
    )

T = TypeVar("T", "CommandArgs", "SessionArgs")

#: Keys and parameters names
KW_DEFAULT: Literal["default"] = "default"
KW_MATRIX: Literal["matrix"] = "matrix"
KW_PY: Literal["py"] = "py"
KW_REQUIRES: Literal["requires"] = "requires"
KW_REUSE_VENV: Literal["reuse_venv"] = "reuse_venv"
KW_VENV_BACKEND: Literal["venv_backend"] = "venv_backend"
KW_VENV_PARAMS: Literal["venv_params"] = "venv_params"
KW_TAGS: Literal["tags"] = "tags"

#: Key-value arguments both common to :class:`nox.sessions.Session` and
#: :class:`~vutils.nox.command.Command`
COMMON_KWARGS = (KW_NAME,)

#: Key-value arguments used only by :class:`~vutils.nox.command.Command`
COMMAND_ONLY_KWARGS = (
    KW_INSTALL_MODE,
    KW_DESCRIPTION,
    KW_ENVNAME,
    KW_PACKAGE,
    KW_CACHEDIR,
    KW_CONFIG,
    KW_ACTIONS,
    KW_STATEFILE,
)

#: Key-value arguments used only by :class:`nox.sessions.Session`
SESSION_ONLY_KWARGS = (
    KW_PYTHON,
    KW_PY,
    KW_REUSE_VENV,
    KW_VENV_BACKEND,
    KW_VENV_PARAMS,
    KW_TAGS,
    KW_DEFAULT,
    KW_REQUIRES,
)

#: Special dependencies names
FROM_PYPROJECT = "pyproject"


def __ensure_defs(cls: type[Command]) -> None:
    """
    Ensure that ``DEFS`` is in every subclass.

    :param cls: The :class:`~vutils.nox.command.Command`-based class

    Ensure that every base of :xarg:`cls`, which is a subclass of
    :class:`~vutils.nox.command.Command`, has its own
    :attr:`Command.DEFS <vutils.nox.command.Command.DEFS>` class variable. This
    makes sure that dependencies and configuration are added correctly to
    user-defined commands and not cumulated in the base class.
    """
    bases = [base for base in cls.__mro__ if issubclass(base, Command)]
    origin = bases.pop()
    while bases:
        if bases[-1].DEFS is origin.DEFS:
            bases[-1].DEFS = {KW_DEPS: {}, KW_CONF: {}}
        origin = bases.pop()


def __is_common_kwarg(kwarg: str) -> TypeGuard["CommonArgsKey"]:
    """
    Check whether the key-value argument is a common one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is common to the both of
        :class:`nox.sessions.Session` and :class:`~vutils.nox.command.Command`
    """
    return kwarg in COMMON_KWARGS


def __is_command_only_kwarg(kwarg: str) -> TypeGuard["CommandArgsOnlyKey"]:
    """
    Check whether the key-value argument is a command-only one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is a
        :class:`~vutils.nox.command.Command`-only key-value argument
    """
    return kwarg in COMMAND_ONLY_KWARGS


def __is_session_only_kwarg(kwarg: str) -> TypeGuard["SessionArgsOnlyKey"]:
    """
    Check whether the key-value argument is a session-only one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is a
        :class:`nox.sessions.Session`-only key-value argument
    """
    return kwarg in SESSION_ONLY_KWARGS


def __split_kwargs(kwargs: "AddArgs") -> tuple["CommandArgs", "SessionArgs"]:
    """
    Split key-value arguments into session and command ones.

    :param kwargs: Key-value arguments coming from :deco:`.add`
    :return: the pair of key-value arguments for
        :class:`~vutils.nox.command.Command` and :class:`nox.sessions.Session`
        made from :xarg:`kwargs`
    :raises ValueError: when :xarg:`kwargs` contains an unexpected key
    """
    command_kwargs: CommandArgs = {}
    session_kwargs: SessionArgs = {}

    for key in kwargs:
        if __is_common_kwarg(key):
            session_kwargs[key] = kwargs[key]
            command_kwargs[key] = kwargs[key]
        elif __is_command_only_kwarg(key):
            command_kwargs[key] = kwargs[key]
        elif __is_session_only_kwarg(key):
            session_kwargs[key] = kwargs[key]
        else:
            raise ValueError(f"Unexpected key-value argument: {key}")
    return (command_kwargs, session_kwargs)


def __is_command_kwarg(kwarg: str) -> TypeGuard["CommandArgsKey"]:
    """
    Check whether the key-value argument is a command one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is a
        :class:`~vutils.nox.command.Command` key-value argument
    """
    return kwarg in COMMON_KWARGS or kwarg in COMMAND_ONLY_KWARGS


def __is_session_kwarg(kwarg: str) -> TypeGuard["SessionArgsKey"]:
    """
    Check whether the key-value argument is a session one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is a
        :class:`nox.sessions.Session` key-value argument
    """
    return kwarg in COMMON_KWARGS or kwarg in SESSION_ONLY_KWARGS


def __is_command_kwargs(
    unused_kwargs: T, keys: Iterable[str]
) -> TypeGuard["CommandArgs"]:
    """
    Check whether key-value arguments are command key-value arguments.

    :param unused_kwargs: Key-value arguments
    :param keys: Keys
    :return: :obj:`True` if :xarg:`keys` are valid keys of key-value arguments
        of :class:`~vutils.nox.command.Command`

    Helps to narrow key-value arguments to the specified type.
    """
    return set(keys).issubset(set(COMMON_KWARGS) | set(COMMAND_ONLY_KWARGS))


def __is_session_kwargs(
    unused_kwargs: T, keys: Iterable[str]
) -> TypeGuard["SessionArgs"]:
    """
    Check whether key-value arguments are session key-value arguments.

    :param unused_kwargs: Key-value arguments
    :param keys: Keys
    :return: :obj:`True` if :xarg:`keys` are valid keys of key-value arguments
        of :class:`nox.sessions.Session`

    Helps to narrow key-value arguments to the specified type.
    """
    return set(keys).issubset(set(COMMON_KWARGS) | set(SESSION_ONLY_KWARGS))


def __combine(kwargs: T, other: "MatrixArgs", allowed: Iterable[str]) -> T:
    """
    Combine :xarg:`kwargs` with :xarg:`other`.

    :param kwargs: Key-value arguments
    :param other: Other key-value arguments
    :param allowed: The list of names of allowed key-value arguments
    :return: the copy of :xarg:`kwargs` merged with :xarg:`other`
    :raises ValueError: when a key-value argument from :xarg:`other` is already
        present in :xarg:`kwargs`
    :raises TypeError: in case of an invalid combination of :xarg:`kwargs` and
        :xarg:`allowed`
    """
    new_kwargs = kwargs.copy()

    for key in other:
        if key in new_kwargs:
            raise ValueError(f"`{key}` is already specified")
        if key not in COMMON_KWARGS and key not in allowed:
            continue
        if __is_command_kwarg(key) and __is_command_kwargs(
            new_kwargs, allowed
        ):
            new_kwargs[key] = other[key]
        elif __is_session_kwarg(key) and __is_session_kwargs(
            new_kwargs, allowed
        ):
            new_kwargs[key] = other[key]
        else:
            raise TypeError("Invalid arguments combination")
    return new_kwargs


def add(**kwargs: Unpack["AddArgs"]) -> "CommandDecoratorType":
    """
    Create a decorator that adds the command to the Nox session registry.

    :param kwargs: Key-value arguments
    :return: a decorator function

    Key-value arguments accepted by this function are:

    * ``name``, specifying the name of both the command and the session
    * ``envname``, specifying the name of a Python virtual environment under
      which the command is executed
    * ``description``, specifying the description of the command
    * ``actions``, specifying the command actions
    * ``package``, specifying the importable name of the produced Python
      package
    * ``cachedir``, specifying the shared cache directory
    * ``config``, specifying the name of the configuration file for the command
    * ``install_mode``, specifying the installation mode of command's
      dependencies
    * ``statefile``, specifying the name of the file used as the command's
      state persistent storage
    * ``python``, specifying supported Python interpreter version(s) (see the
      `Nox documentation`_ for further details)
    * ``py`` is an alias for ``python``
    * ``reuse_venv``, specifying whether the Python virtual environment should
      be reused
    * ``venv_backend``, specifying the Python virtual environment backend (see
      the `Nox documentation`_ for further details)
    * ``venv_params``, specifying additional parameters for the Python virtual
      environment
    * ``tags``, specifying a list of tags for the session
    * ``default``, specifying whether the session runs by default
    * ``requires``, specifying a list of sessions required to be executed
      before the session
    * ``matrix``, specifying a test matrix

    A test matrix provides a sequence of dictionaries whose keys are
    complementary to :xarg:`kwargs`. That is, if both some dictionary from the
    test matrix and :xarg:`kwargs` have a same key then this is treated as an
    error. For every dictionary in the test matrix, the dictionary is merged
    with the rest of :xarg:`kwargs` and the result is passed again to
    :deco:`.add`. Thus this ::

        @add(
            matrix=(
                {"python": "3.8", "name": "task38"},
                {"python": "python", "name": "task"},
            ),
            reuse_venv=True,
        )
        class Task(Command): ...

    is equivalent to this::

        @add(python="3.8", name="task38", reuse_venv=True)
        @add(python="python", name="task", reuse_venv=True)
        class Task(Command): ...

    A dictionary from a test matrix supports following keys and values:

    * ``name`` (:class:`str`, see the explanation above)
    * ``envname`` (:class:`str`, see the explanation above)
    * ``description`` (:class:`str`, see the explanation above)
    * ``python`` (:class:`str`, a Python version in ``<major>.<minor>`` format
      or ``python`` meaning that the same Python interpreter as that under the
      which Nox were executed is used)
    * ``actions`` (the list of names of previously :deco:`.add`ed commands)
    * ``tags`` (the list of tags, see the explanation above)
    * ``requires`` (see above)

    .. _Nox documentation: https://nox.thea.codes/en/stable/
    """

    def decorator(command: type[Command]) -> type[Command]:
        """
        Add a command to the Nox session registry.

        :param command: The :class:`~vutils.nox.command.Command`-based class
        :return: the :xarg:`command`
        """
        __ensure_defs(command)
        __add(command, **kwargs)
        return command

    return decorator


def __add(command: type[Command], **kwargs: Unpack["AddArgs"]) -> None:
    """
    Add a command to the Nox session registry.

    :param command: The :class:`~vutils.nox.command.Command`-based class
    :param kwargs: Key-value arguments
    """
    matrix = kwargs.pop(KW_MATRIX, ({},))
    command_kwargs, session_kwargs = __split_kwargs(kwargs)

    for row in matrix:
        session_decorator(
            **__combine(session_kwargs, row, SESSION_ONLY_KWARGS)
        )(command(**__combine(command_kwargs, row, COMMAND_ONLY_KWARGS)))


def dep(depname: str, spec: str | None = "") -> "CommandDecoratorType":
    """
    Create a decorator that adds a dependency to the command.

    :param depname: The dependency name
    :param spec: The dependency specifier
    :return: the decorator function

    If the dependency name is ``.``, it means that the dependency is the local
    Python package source installable via ``pip install -e .``. If the
    dependency name is ``./dist``, it means that the dependency is the local
    Python package binary wheel distribution that can be found under the
    ``dist`` directory produced during the building the package. If the
    dependency name starts with ``%``, it means it is the special case (see
    further). Otherwise, the dependency name refers to a Python package from
    the Python package index (without specifiers).

    The special cases of dependencies:

    * ``%pyproject``, meaning that the dependencies and their specifiers are
      loaded from ``pyproject.toml`` from the ``project.dependencies`` field.
      Note that when :xarg:`spec` is :obj:`None` then :obj:`None` overrides all
      specifiers of loaded dependencies, meaning that the dependencies will be
      removed from the set instead of added.

    The dependecy specifier has the following semantics:

    * If it is :obj:`None`, the dependency is removed from the set.
    * If it is the empty string ``""`` (the default value of :xarg:`spec`),
      there is no specifier associated with the dependency (the Python package
      manager decides which version to install). This is mandatory for local
      Python packages. This specifier will not nullify previous specifiers but
      it is rather ignored if there are some.
    * Otherwise, it must be valid PEP 508 dependency specifier.

      * If it starts with ``>`` (leading spaces are not considered), the
        dependency is treated as a security update and it is installed in its
        own batch, before all other dependencies are installed.
    """

    def decorator(command: type[Command]) -> type[Command]:
        """
        Add a dependency to the command.

        :param command: The :class:`~vutils.nox.command.Command`-based class
        :return: the :xarg:`command`
        """
        __ensure_defs(command)
        __dep(command, depname, spec)
        return command

    return decorator


def __dep(command: type[Command], depname: str, spec: str | None) -> None:
    """
    Add a dependency to the command.

    :param command: The :class:`~vutils.nox.command.Command`-based class
    :param depname: The dependency name
    :param spec: The dependency specifier
    :raises ValueError: when arguments are ill-formed
    """
    depname = depname.strip()
    if depname == "":
        raise ValueError("Dependency name must not be empty")

    if depname.startswith("%"):
        dep_spec: tuple[str, str]
        for dep_spec in __dep_special(depname[1:]):
            __dep(
                command, dep_spec[0], dep_spec[1] if spec is not None else None
            )
        return

    if isinstance(spec, str):
        spec = spec.strip()
    if (
        depname in {".", f"./{DIST_DIR_NAME}"}
        and spec is not None
        and spec != ""
    ):
        raise ValueError(
            "Dependency specifier must be either empty string or `None`"
        )

    if depname == ".":
        pkg_name = "."
        pkg_spec = None if spec is None else LocalDist()
    elif depname == f"./{DIST_DIR_NAME}":
        pkg_name = "."
        pkg_spec = None if spec is None else LocalDist(DistKind.WHEEL)
    elif spec is not None and spec.startswith(">"):
        pkg_name = depname
        pkg_spec = Security(spec)
    else:
        pkg_name = depname
        pkg_spec = spec
    command.DEFS[KW_DEPS][pkg_name] = pkg_spec


def __dep_special(depname: str) -> Generator[tuple[str, str], None, None]:
    """
    Handle the special dependency case.

    :param depname: The special dependency case name
    :return: the generator yielding pairs where each pair contains the
        dependency name and specifier
    :raises ValueError: when :xarg:`depname` is not a valid special dependency
        case name
    """
    depname = depname.strip()
    if depname == FROM_PYPROJECT:
        for req in project_dependencies():
            yield (req.name, str(req)[len(req.name) :].strip())
    else:
        raise ValueError(f"Unknown special dependency case name: %{depname}")


def cfg(path: str, item: object) -> "CommandDecoratorType":
    """
    Create a decorator that adds a configuration item to the command.

    :param path: The path to the configuration item
    :param item: The configuration item
    :return: the decorator function

    Path segments are separated by ``::``. For instance this ::

        @cfg("black :: line-length", 79)
        class Task(Command): ...

    is roughly an equivalent for::

        Task.DEFS["conf"]["black"]["line-length"] = 79

    If :xarg:`item` is :class:`~vutils.nox.command.RemoveMarker`, the item on
    :xarg:`path` is deleted.
    """

    def decorator(command: type[Command]) -> type[Command]:
        """
        Add a configuration item to the command.

        :param command: The :class:`~vutils.nox.command.Command`-based class
        :return: the :xarg:`command`
        """
        __ensure_defs(command)
        __cfg(command, path, item)
        return command

    return decorator


def __cfg(command: type[Command], path: str, item: object) -> None:
    """
    Add a configuration item to the command.

    :param command: The :class:`~vutils.nox.command.Command`-based class
    :param path: The path to the configuration item
    :param item: The configuration item
    """
    container, key = container_at_path(command.DEFS[KW_CONF], path)
    container[key] = item
