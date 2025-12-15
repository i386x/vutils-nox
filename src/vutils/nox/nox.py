#
# File:    ./src/vutils/nox/nox.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-01 02:30:06 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Nox tweaks."""

import sys

from nox._decorators import Func
from nox.sessions import _normalize_path
from nox.sessions import SessionRunner as NoxSessionRunner

from vutils.nox.command import Command


class SessionRunner(NoxSessionRunner):
    """Tweaked :class:`nox.sessions.SessionRunner`."""

    __slots__ = ()

    def __resolve_envname(self) -> str:
        """
        Resolve the name of a Python virtual environment.

        :return: the name of the Python virtual environment
        """
        if isinstance(self.func, Func) and isinstance(self.func.func, Command):
            return self.func.func.envname
        return self.friendly_name

    @property
    def envdir(self) -> str:
        """
        Return the path to the Python environment directory.

        :return: the path to the Python environment directory
        """
        return _normalize_path(
            self.global_config.envdir, self.__resolve_envname()
        )


def patch_nox(old: object, new: object) -> None:
    """
    Patch the Nox modules.

    :param old: The old object
    :param new: The new object

    Go throw all imported Nox modules, find all occurrences of :xarg:`old`,
    based on its ``__name__``, and replace it with :xarg:`new`.
    """
    for modname in sys.modules:
        if (
            modname.startswith("nox")
            and getattr(sys.modules[modname], old.__name__, None) is old
        ):
            setattr(sys.modules[modname], old.__name__, new)


def setup() -> None:
    """Setup the Nox to be ``vutils-nox`` ready."""
    patch_nox(NoxSessionRunner, SessionRunner)
