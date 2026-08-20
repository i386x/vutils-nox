#
# File:    ./src/vutils/nox/mypy/transforms.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-07-31 07:50:08 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Type transformers."""

from mypy.types import Type


class CaptureType[T: Type, *Ts]:
    """The action for capturing types during type pattern matching."""

    #: The captured type
    __type: T | None

    __slots__ = ("__type",)

    def __init__(self) -> None:
        """Initialize the action."""
        self.reset()

    def reset(self) -> None:
        """Reset the action."""
        self.__type = None

    def get(self) -> T:
        """
        Get the captured type.

        :return: the captured type
        :raises TypeError: when there is no captured type yet
        """
        if self.__type is None:
            raise TypeError("A type has not been captured yet")
        return self.__type

    def __call__(self, t: T, *unused_args: *Ts) -> Type:
        """
        Capture the type.

        :param t: The type to be captured
        :param unused_args: The rest of action arguments (unused)
        :return: :xarg:`t`
        """
        self.__type = t
        return t
