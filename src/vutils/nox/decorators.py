#
# File:    ./src/vutils/nox/decorators.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-11-03 01:58:18 +0100
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Decorators."""

import functools
from typing import TYPE_CHECKING, overload

from nox.registry import session_decorator

from vutils.nox.command import (
    KW_ACTIONS,
    KW_CACHEDIR,
    KW_CONFIG,
    KW_DESCRIPTION,
    KW_ENVNAME,
    KW_INSTALL_MODE,
    KW_NAME,
    KW_PACKAGE,
    KW_ROOTDIR,
    KW_STATEFILE,
    Command,
)
from vutils.nox.utils import KW_PYTHON

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import Literal, TypeGuard, TypeVar, Unpack

    from vutils.nox import (
        AddArgs,
        CommandArgs,
        CommandArgsKey,
        CommandArgsOnlyKey,
        CommonArgsKey,
        MatrixArgs,
        SessionArgs,
        SessionArgsKey,
        SessionArgsOnlyKey,
    )

    T = TypeVar("T", CommandArgs, SessionArgs)

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
COMMON_KWARGS: Iterable[str] = (KW_NAME,)
#: Key-value arguments used only by :class:`~vutils.nox.command.Command`
COMMAND_ONLY_KWARGS: Iterable[str] = (
    KW_INSTALL_MODE,
    KW_DESCRIPTION,
    KW_ENVNAME,
    KW_PACKAGE,
    KW_ROOTDIR,
    KW_CACHEDIR,
    KW_CONFIG,
    KW_ACTIONS,
    KW_STATEFILE,
)
#: Key-value arguments used only by :class:`nox.sessions.Session`
SESSION_ONLY_KWARGS: Iterable[str] = (
    KW_PYTHON,
    KW_PY,
    KW_REUSE_VENV,
    KW_VENV_BACKEND,
    KW_VENV_PARAMS,
    KW_TAGS,
    KW_DEFAULT,
    KW_REQUIRES,
)


def __is_common_kwarg(kwarg: str) -> TypeGuard[CommonArgsKey]:
    """
    Check whether the key-value argument is a common one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is common to the both of
        :class:`nox.sessions.Session` and :class:`~vutils.nox.command.Command`
    """
    return kwarg in COMMON_KWARGS


def __is_command_only_kwarg(kwarg: str) -> TypeGuard[CommandArgsOnlyKey]:
    """
    Check whether the key-value argument is a command-only one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is a
        :class:`~vutils.nox.command.Command`-only key-value argument
    """
    return kwarg in COMMAND_ONLY_KWARGS


def __is_session_only_kwarg(kwarg: str) -> TypeGuard[SessionArgsOnlyKey]:
    """
    Check whether the key-value argument is a session-only one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is a
        :class:`nox.sessions.Session`-only key-value argument
    """
    return kwarg in SESSION_ONLY_KWARGS


def __split_kwargs(kwargs: AddArgs) -> tuple[CommandArgs, SessionArgs]:
    """
    Split key-value arguments into session and command ones.

    :param kwargs: Key-value arguments coming from :func:`.add`
    :return: the pair of key-value arguments for
        :class:`~vutils.nox.command.Command` and :class:`nox.sessions.Session`
        made from :xarg:`kwargs`
    :raises ValueError: when :xarg:`kwargs` contains an unexpected key
    """
    command_kwargs: CommandArgs = {}
    session_kwargs: SessionArgs = {}

    key: str
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


def __is_command_kwarg(kwarg: str) -> TypeGuard[CommandArgsKey]:
    """
    Check whether the key-value argument is a command one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is a
        :class:`~vutils.nox.command.Command` key-value argument
    """
    return kwarg in COMMON_KWARGS or kwarg in COMMAND_ONLY_KWARGS


def __is_session_kwarg(kwarg: str) -> TypeGuard[SessionArgsKey]:
    """
    Check whether the key-value argument is a session one.

    :param kwarg: The key-value argument name
    :return: :obj:`True` if the key-value argument is a
        :class:`nox.sessions.Session` key-value argument
    """
    return kwarg in COMMON_KWARGS or kwarg in SESSION_ONLY_KWARGS


def __is_command_kwargs(
    unused_kwargs: T, keys: Iterable[str]
) -> TypeGuard[CommandArgs]:
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
) -> TypeGuard[SessionArgs]:
    """
    Check whether key-value arguments are session key-value arguments.

    :param unused_kwargs: Key-value arguments
    :param keys: Keys
    :return: :obj:`True` if :xarg:`keys` are valid keys of key-value arguments
        of :class:`nox.sessions.Session`

    Helps to narrow key-value arguments to the specified type.
    """
    return set(keys).issubset(set(COMMON_KWARGS) | set(SESSION_ONLY_KWARGS))


def __combine(kwargs: T, other: MatrixArgs, allowed: Iterable[str]) -> T:
    """
    Combine :xarg:`kwargs` with :xarg:`other`.

    :param kwargs: Key-value arguments
    :param other: Other key-value arguments
    :param allowed: The list of names of allowed key-value arguments
    :return: the copy of :xarg:`kwargs` merged with :xarg:`other`
    :raises ValueError: when a key-value argument from :xarg:`other` is already
        present in :xarg:`kwargs` or if it is not in :xarg:`allowed` (note that
        key-value arguments from :const:`.COMMON_KWARGS` are always allowed)
    :raises TypeError: in case of an invalid combination of :xarg:`kwargs` and
        :xarg:`allowed`
    """
    new_kwargs: T = kwargs.copy()

    key: str
    for key in other:
        if key in new_kwargs:
            raise ValueError(f"`{key}` is already specified")
        if key not in COMMON_KWARGS and key not in allowed:
            raise ValueError(f"`{key}` is not allowed here")
        if (
            __is_command_kwarg(key)
            and __is_command_kwargs(new_kwargs, allowed)
        ):
            new_kwargs[key] = other[key]
        elif (
            __is_session_kwarg(key)
            and __is_session_kwargs(new_kwargs, allowed)
        ):
            new_kwargs[key] = other[key]
        else:
            raise TypeError("Invalid arguments combination")
    return new_kwargs


@overload
def add(command: type[Command], /) -> type[Command]: ...


@overload
def add(
    command: None = None, /, **kwargs: Unpack[AddArgs]
) -> Callable[[type[Command]], type[Command]]: ...


def add(
    command: type[Command] | None = None, **kwargs: Unpack[AddArgs]
) -> Callable[[type[Command]], type[Command]] | type[Command]:
    """
    Add command to the Nox session registry.

    :param command: The :class:`~vutils.nox.command.Command`-based class
    :param kwargs: Key-value arguments
    :return: a decorator function or :xarg:`command`

    When used like::

        @add(...)
        class Task(Command): ...

    it returns the decorator function that is then applied on `Task`. When used
    like::

        @add
        class Task(Command): ...

    it itself treats as the decorator function.

    Key-value arguments accepted by this decorator function are:

    * ``name``
    """
    if command is None:
        return functools.partial(add, **kwargs)
    matrix: Iterable[MatrixArgs] = kwargs.pop(KW_MATRIX, ({},))

    command_kwargs: CommandArgs
    session_kwargs: SessionArgs
    command_kwargs, session_kwargs = __split_kwargs(kwargs)

    row: MatrixArgs
    for row in matrix:
        session_decorator(
            **__combine(session_kwargs, row, SESSION_ONLY_KWARGS)
        )(command(**__combine(command_kwargs, row, COMMAND_ONLY_KWARGS)))
    return command
