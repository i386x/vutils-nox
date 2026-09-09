#
# File:    ./src/vutils/nox/mypy/transforms.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-07-31 07:50:08 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Type transformers."""

from collections.abc import Sequence

from mypy.types import Instance, LiteralType, Type


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


class ModifyInstance:
    """The action for modifying :class:`mypy.types.Instance` types."""

    #: The new instance type arguments
    args: Sequence[Type] | None
    #: The new *last known value*
    last_known_value: LiteralType | None

    __slots__ = ("args", "last_known_value")

    def __init__(
        self,
        args: Sequence[Type] | None = None,
        last_known_value: LiteralType | None = None,
    ) -> None:
        """
        Initialize the action.

        :param args: The new instance type arguments
        :param last_known_value: The new *last known value*

        When invoked, the action replaces the arguments and the *last known
        value* of the passed instance type with :xarg:`args` and
        :xarg:`last_known_value`, respectively. If a new provided value is
        :obj:`None`, the old value is used.
        """
        self.args = args
        self.last_known_value = last_known_value

    def __call__(
        self,
        t: Instance,
        args: Sequence[Type],
        last_known_value: LiteralType | None,
    ) -> Type:
        """
        Modify :xarg:`t` when necessary.

        :param t: The instance type
        :param args: The instance type arguments
        :param last_known_value: The instance type *last known value*
        :return: :xarg:`t` or modified :xarg:`t`
        """
        if self.args is None and self.last_known_value is None:
            return t
        return Instance(
            typ=t.type,
            args=args if self.args is None else self.args,
            line=t.line,
            column=t.column,
            last_known_value=(
                last_known_value
                if self.last_known_value is None
                else self.last_known_value
            ),
            extra_attrs=t.extra_attrs,
        )
