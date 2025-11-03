#
# File:    ./src/vutils/nox/__init__.pyi
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-09-30 19:13:09 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#

from collections.abc import Callable, Iterable, MutableMapping
from os import PathLike
from typing import TypedDict

from nox.sessions import Session
from typing_extensions import TypeAlias

from vutils.nox.command import Command
from vutils.nox.pkgspec import InstallMode, LocalDist, Security

StrPath: TypeAlias = str | PathLike[str]

CommandBaseType: TypeAlias = type[Command] | type[object]
PkgSpecType: TypeAlias = LocalDist | Security | str | None
ActionType: TypeAlias = Callable[[Command, Session], None]
DepsType: TypeAlias = MutableMapping[str, PkgSpecType]
ConfType: TypeAlias = MutableMapping[str, object]

class CommandOptions(TypedDict, total=False):
    install_mode: InstallMode

class CommandProps(CommandOptions, total=False):
    name: str
    description: str
    envname: str
    package: str
    rootdir: PathLike[str]
    cachedir: PathLike[str]
    config: str | None

class CommandArgs(CommandProps, total=False):
    actions: Iterable[ActionType]

class CommandDefs(TypedDict):
    deps: DepsType
    conf: ConfType
