#
# File:    ./src/vutils/nox/typing.pyi
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-09-30 19:13:09 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#

from collections.abc import Callable, Iterable, MutableMapping, Sequence
from os import PathLike
from typing import Literal, Protocol, TypeAlias, TypedDict

from nox._typing import Python
from nox.sessions import Session

from vutils.nox.command import Command
from vutils.nox.pkgspec import InstallMode, LocalDist, Security
from vutils.nox.state import CommandState

StrPath: TypeAlias = str | PathLike[str]

class TypesFunctionType(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> object: ...

CommandBaseType: TypeAlias = type[Command | object]
PkgSpecType: TypeAlias = LocalDist | Security | str | None
ActionType: TypeAlias = Callable[[Command, Session, CommandState | None], None]
DepsType: TypeAlias = MutableMapping[str, PkgSpecType]
ConfType: TypeAlias = MutableMapping[str, object]
CommandDecoratorType: TypeAlias = Callable[[type[Command]], type[Command]]

CommonArgsKey: TypeAlias = Literal["name"]
CommandArgsOnlyKey: TypeAlias = Literal[
    "install_mode",
    "description",
    "envname",
    "package",
    "cachedir",
    "config",
    "actions",
    "statefile",
]
CommandArgsKey: TypeAlias = CommonArgsKey | CommandArgsOnlyKey
SessionArgsOnlyKey: TypeAlias = Literal[
    "python",
    "py",
    "reuse_venv",
    "venv_backend",
    "venv_params",
    "tags",
    "default",
    "requires",
]
SessionArgsKey: TypeAlias = CommonArgsKey | SessionArgsOnlyKey

class CommonArgs(TypedDict, total=False):
    name: str

class CommandOptions(TypedDict, total=False):
    install_mode: InstallMode

class CommandPropsBase(CommandOptions, total=False):
    description: str
    envname: str
    package: str
    cachedir: PathLike[str]
    config: str

class CommandProps(CommonArgs, CommandPropsBase, total=False): ...

class CommandArgsBase(CommandPropsBase, total=False):
    actions: Iterable[ActionType | str]
    statefile: str

class CommandArgs(CommonArgs, CommandArgsBase, total=False): ...

class SessionArgsBase(TypedDict, total=False):
    python: Python
    py: Python
    reuse_venv: bool
    venv_backend: str
    venv_params: Sequence[str]
    tags: Sequence[str]
    default: bool
    requires: Sequence[str]

class SessionArgs(CommonArgs, SessionArgsBase, total=False): ...

class MatrixArgs(TypedDict, total=False):
    name: str
    description: str
    envname: str
    actions: Sequence[str]
    python: str
    tags: Sequence[str]
    requires: Sequence[str]

class AddArgs(CommonArgs, CommandArgsBase, SessionArgsBase, total=False):
    matrix: Iterable[MatrixArgs]

class CommandDefs(TypedDict):
    deps: DepsType
    conf: ConfType
