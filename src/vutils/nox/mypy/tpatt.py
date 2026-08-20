#
# File:    ./src/vutils/nox/mypy/tpatt.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-07-31 07:50:00 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Patterns and matching over types."""

from collections.abc import Callable, Sequence

from mypy.nodes import ARG_POS, ARG_STAR, ARG_STAR2, ArgKind, TypeAlias
from mypy.types import (
    CallableType,
    Instance,
    LiteralType,
    Type,
    TypeAliasType,
    TypeVarLikeType,
    TypeVarType,
    UnionType,
)

from vutils.nox.mypy.utils import OBJECT_TYPE, verify_type

#: Type aliases
type InstanceAction = Callable[
    [Instance, Sequence[Type], LiteralType | None], Type
]
type CallableAction = Callable[
    [CallableType, Sequence[Type], Type, Sequence[TypeVarLikeType]], Type
]
type UnionAction = Callable[[UnionType, Sequence[Type]], Type]
type TypeVarAction = Callable[
    [TypeVarType, Type, Sequence[Type], Type], Type
]
type TypeAliasAction = Callable[
    [TypeAliasType, TypeAlias, Sequence[Type]], Type
]


class TypeMatchError(TypeError):
    """Error signaling that the type does not match the given pattern."""


def check[T: Type](t: Type, tt: type[T], fullname: str | None = None) -> T:
    """
    Check whether :xarg:`t` matches the given type.

    :param t: The type to be checked
    :param tt: The expected type
    :param fullname: The expected full name of the type in case the type is
        :class:`mypy.types.Instance`
    :return: the type narrowed to the expected type
    :raises .TypeMatchError: when the check fails

    When :xarg:`fullname` is :obj:`None`, the full name part of the check is
    skipped.
    """
    if not isinstance(t, tt):
        raise TypeMatchError(f"Expected `{tt!r}` type")
    if isinstance(t, Instance):
        if fullname is not None and t.type.fullname != fullname:
            raise TypeMatchError(f"Expected `Instance({fullname})`")
    return t


class Pattern[T: Type | Sequence[Type]]:
    """The base of all type patterns."""

    __slots__ = ()

    def __init__(self) -> None:
        """Initialize the pattern base."""

    def match(self, t: T) -> T:
        """
        Match a type or a sequence of types.

        :param t: The type or the sequence of types
        :return: :xarg:`t` or a modified copy of :xarg:`t` or a custom result
            based on :xarg:`t` returned by the user-defined action
        :raises .TypeMatchError: on an unsuccessful match

        Match :xarg:`t` and invoke the user-defined action when provided.
        """
        raise NotImplementedError

    def test(self, t: T) -> bool:
        """
        Test whether :xarg:`t` matches the pattern.

        :param t: The type or the sequence of types.
        :return: :obj:`True` if :xarg:`t` matches the pattern

        This operation also involves invoking user-defined actions.
        """
        try:
            self.match(t)
        except TypeMatchError:
            return False
        return True

    def __or__(self: Pattern[Type], other: Pattern[Type]) -> UnionTypePattern:
        """
        Make a pattern for a union of types.

        :param other: The type pattern
        :return: the pattern for a union of types made from this and
            :xarg:`other` type patterns

        Take this and :xarg:`other` type patterns and pass them as :xarg:`items
        <.UnionTypePattern.__init__:args>` to :class:`.UnionTypePattern`. If
        any of this or :xarg:`other` type patterns is an instance of
        :class:`.UnionTypePattern`, their items are flattened. The action is
        inherited either from this type pattern or from :xarg:`other`,
        depending on which of them is an instance of
        :class:`.UnionTypePattern`, respectively. If none of them is an
        instance of :class:`.UnionTypePattern`, no action is set.
        """
        action: UnionAction | None = None
        if isinstance(self, UnionTypePattern):
            action = self.action
        elif isinstance(other, UnionTypePattern):
            action = other.action
        return UnionTypePattern(
            *self.items.patterns if isinstance(self, UnionTypePattern)
            else self,
            *other.items.patterns if isinstance(other, UnionTypePattern)
            else other,
            action=action,
        )


class Many[T: Type](Pattern[Sequence[T]]):
    """A pattern for homogeneous sequence of types."""

    #: The pattern for the underlying type of the sequence
    pattern: Pattern[T]

    __slots__ = ("pattern",)

    def __init__(self, pattern: Pattern[T]) -> None:
        """
        Initialize the pattern.

        :param pattern: The pattern for the underlying type of the sequence
        """
        super().__init__()
        self.pattern = pattern

    def match(self, seq: Sequence[T]) -> Sequence[T]:
        """
        Match the sequence of types.

        :param seq: The sequence of types
        :return: the sequence of types where each type is either an element of
            :xarg:`seq` or a modified copy of an element of :xarg:`seq` or a
            custom type based on the element of :xarg:`seq` returned by the
            user-defined action
        :raises .TypeMatchError: on the first unsuccessful match
        """
        return list(map(self.pattern.match, seq))


class Seq[T: Type](Pattern[Sequence[T]]):
    """A pattern for finite heterogeneous sequence of types."""

    #: The sequence of patterns
    patterns: Sequence[Pattern[T]]

    __slots__ = ("patterns",)

    def __init__(self, patterns: Sequence[Pattern[T]]) -> None:
        """
        Initialize the pattern.

        :param patterns: The sequence of patterns

        Each pattern from :xarg:`patterns` must match the corresponding type
        from the given sequence of types.
        """
        super().__init__()
        self.patterns = patterns

    def match(self, seq: Sequence[T]) -> Sequence[T]:
        """
        Match the sequence of types.

        :param seq: The sequence of types
        :return: the sequence of types where each type is either an element of
            :xarg:`seq` or a modified copy of an element of :xarg:`seq` or a
            custom type based on the element of :xarg:`seq` returned by the
            user-defined action
        :raises .TypeMatchError: on the first unsuccessful match
        """
        if len(self.patterns) != len(seq):
            raise TypeMatchError(f"Sequences are of different lengths")
        return [p.match(t) for p, t in zip(self.patterns, seq)]


class InstancePattern(Pattern[Type]):
    """A pattern for :class:`mypy.types.Instance` types."""

    #: The full name of the instance type
    fullname: str | None
    #: The pattern for the instance type arguments
    args: Pattern[Sequence[Type]] | None
    #: The pattern for the *last known value*
    last_known_value: Pattern[Type] | None
    #: The action to be invoked on a successful match
    action: InstanceAction | None

    __slots__ = ("fullname", "args", "last_known_value", "action")

    def __init__(
        self,
        fullname: str | None = None,
        args: Pattern[Sequence[Type]] | None = None,
        last_known_value: Pattern[Type] | None = None,
        action: InstanceAction | None = None,
    ) -> None:
        """
        Initialize the pattern.

        :param fullname: The full name of the instance type
        :param args: The pattern for the instance type arguments
        :param last_known_value: The pattern for the *last known value*
        :param action: The action to be invoked on a successful match

        If any of parameters is :obj:`None`, then the matching against this
        parameter is skipped.
        """
        super().__init__()
        self.fullname = fullname
        self.args = args
        self.last_known_value = last_known_value
        self.action = action

    def match(self, t: Type) -> Type:
        """
        Match the instance type.

        :param t: The instance type
        :return: :xarg:`t` or a modified copy of :xarg:`t` or a custom type
            based on :xarg:`t` returned by the user-defined action
        :raises .TypeMatchError: on an unsuccessful match
        :raises TypeError: on an unexpected type that appears during matching
        """
        tt = check(t, Instance, self.fullname)
        if (
            self.args is None
            and self.last_known_value is None
            and self.action is None
        ):
            return tt
        args = self.args.match(tt.args) if self.args else tt.args
        last_known_value = tt.last_known_value
        if last_known_value is not None:
            last_known_value = (
                verify_type(
                    self.last_known_value.match(last_known_value),
                    LiteralType,
                )
                if self.last_known_value
                else last_known_value
            )
        if self.action:
            return self.action(tt, args, last_known_value)
        return Instance(
            typ=tt.type,
            args=args,
            line=tt.line,
            column=tt.column,
            last_known_value=last_known_value,
            extra_attrs=tt.extra_attrs,
        )


class Arg:
    """A pattern for an argument of a callable type."""

    #: The argument kind
    kind: ArgKind | None
    #: The pattern for the argument type
    typ: Pattern[Type] | None
    #: The argument name
    name: str | None

    __slots__ = ("kind", "typ", "name")

    def __init__(
        self,
        kind: ArgKind | None = None,
        typ: Pattern[Type] | None = None,
        name: str | None = None,
    ) -> None:
        """
        Initialize the pattern.

        :param kind: The argument kind
        :param typ: The pattern for the argument type
        :param name: The argument name

        If any of parameters is :obj:`None`, then the matching against this
        parameter is skipped.

        If the argument name should be matched to :obj:`None`, pass the empty
        string as the value of :xarg:`name`.
        """
        self.kind = kind
        self.typ = typ
        self.name = name

    def match(self, kind: ArgKind, typ: Type, name: str | None) -> Type:
        """
        Match the argument of a callable type.

        :param kind: The argument kind
        :param typ: The argument type
        :param name: The argument name
        :return: :xarg:`typ` or a modified copy of :xarg:`typ` or a custom type
            based on :xarg:`typ` returned by the user-defined action
        :raises .TypeMatchError: on an unsuccessful match
        """
        if self.kind is not None:
            if kind != self.kind:
                raise TypeMatchError(f"Argument kind mismatch")
        if self.name is not None:
            if name is None and self.name != ""
            or name is not None and name != self.name:
                raise TypeMatchError(f"Argument name mismatch")
        if self.typ:
            return self.typ.match(typ)
        return typ


class Args:
    """A pattern for arguments of a callable type."""

    #: The sequence of argument patterns
    args: Sequence[Arg]

    __slots__ = ("args",)

    def __init__(self, *args: Arg) -> None:
        """
        Initialize the pattern.

        :param args: Argument patterns
        """
        self.args = args

    def match(self, t: CallableType) -> Sequence[Type]:
        """
        Match the arguments of a callable type.

        :param t: The callable type
        :return: the sequence of argument types where each type is either an
            original argument type or its modified copy or a custom type
            based on the original argument type returned by the user-defined
            action
        :raises .TypeMatchError: on the first unsuccessful match
        """
        if len(args) != len(t.arg_kinds):
            raise TypeMatchError(f"The number of arguments does not match")
        return [
            arg.match(kind, typ, name)
            for arg, kind, typ, name in zip(
                args, t.arg_kinds, t.arg_types, t.arg_names
            )
        ]


class CallableTypePattern(Pattern[Type]):
    """A pattern for :class:`mypy.types.CallableType` types."""

    #: The pattern for arguments of a callable type
    args: Args | None
    #: The pattern for the return type of a callable type
    ret_type: Pattern[Type] | None
    #: The pattern for type variables of a callable type
    variables: Pattern[Sequence[TypeVarLikeType]] | None
    #: The action to be invoked on a successful match
    action: CallableAction | None

    __slots__ = ("args", "ret_type", "variables", "action")

    def __init__(
        self,
        *args: Arg | None,
        ret_type: Pattern[Type] | None = None,
        variables: Pattern[Sequence[TypeVarLikeType]] | None = None,
        action: CallableAction | None,
    ) -> None:
        """
        Initialize the pattern.

        :param args: The pattern for arguments of a callable type
        :param ret_type: The pattern for the return type of a callable type
        :param variables: The pattern for type variables of a callable type
        :param action: The action to be invoked on a successful match

        If any argument from :xarg:`args` is :obj:`None`, the matching of such
        argument is skipped. However, the arguments must still match in their
        counts. To skip arguments matching completely, the exception to this
        rule has been added: arguments matching is skipped completely if
        :xarg:`args` contains :obj:`None` as its only element. To ignore
        singleton argument but not arguments count, use ``Arg()`` instead of
        :obj:`None`.

        If any from the rest parameters is :obj:`None`, the matching against
        this parameter is skipped.
        """
        super().__init__()
        if len(args) == 1 and args[0] is None:
            self.args = None
        else:
            self.args = Args(*((arg or Arg()) for arg in args))
        self.ret_type = ret_type
        self.variables = variables
        self.action = action

    def match(self, t: Type) -> Type:
        """
        Match the callable type.

        :param t: The callable type
        :return: :xarg:`t` or a modified copy of :xarg:`t` or a custom type
            based on :xarg:`t` returned by the user-defined action
        :raises .TypeMatchError: on an unsuccessful match
        """
        tt = check(t, CallableType)
        if (
            self.args is None
            and self.ret_type is None
            and self.variables is None
            and self.action is None
        ):
            return tt
        arg_types = self.args.match(tt) if self.args else tt.arg_types
        ret_type = (
            self.ret_type.match(tt.ret_type) if self.ret_type else tt.ret_type
        )
        variables = (
            self.variables.match(tt.variables)
            if self.variables else tt.variables
        )
        if self.action:
            return self.action(tt, arg_types, ret_type, variables)
        return tt.copy_modified(
            arg_types=arg_types, ret_type=ret_type, variables=variables
        )


class UnionTypePattern(Pattern[Type]):
    """A pattern for :class:`mypy.types.UnionType` types."""

    #: The pattern for types in the union of types
    items: Seq[Type]
    #: The action to be invoked on a successful match
    action: UnionAction | None

    __slots__ = ("items", "action")

    def __init__(
        self, *args: Pattern[Type], action: UnionAction | None = None
    ) -> None:
        """
        Initialize the pattern.

        :param args: Patterns for types in the union of types
        :param action: The action to be invoked on a successful match
        """
        self.items = Seq(args)
        self.action = action

    def match(self, t: Type) -> Type:
        """
        Match the union of types.

        :param t: The union of types
        :return: a modified copy of :args:`t` or a custom type based on
            :xarg:`t` returned by the user-defined action
        :raises .TypeMatchError: on an unsuccessful match
        """
        tt = check(t, UnionType)
        items = self.items.match(tt.items)
        if self.action:
            return self.action(tt, items)
        return UnionType(
            items,
            line=tt.line,
            column=tt.column,
            is_evaluated=tt.is_evaluated,
            uses_pep604_syntax=tt.uses_pep604_syntax,
        )


class TypeVarTypePattern(Pattern[Type]):
    """A pattern for :class:`mypy.types.TypeVarType` types."""

    #: The full name of a type variable
    fullname: str | None
    #: The pattern for the upper bound of a type variable
    upper_bound: Pattern[Type] | None
    #: The pattern for the value restrictions of a type variable
    values: Pattern[Sequence[Type]] | None
    #: The pattern for the default value of a type variable
    default: Pattern[Type] | None
    #: The action to be invoked on a successful match
    action: TypeVarAction | None

    __slots__ = ("fullname", "upper_bound", "values", "default", "action")

    def __init__(
        self,
        fullname: str | None = None,
        upper_bound: Pattern[Type] | None = None,
        values: Pattern[Sequence[Type]] | None = None,
        default: Pattern[Type] | None = None,
        action: TypeVarAction | None = None,
    ) -> None:
        """
        Initialize the pattern.

        :param fullname: The full name of a type variable
        :param upper_bound: The pattern for the upper bound of a type variable
        :param values: The pattern for the value restrictions of a type
            variable
        :param default: The pattern for the default value of a type variable
        :param action: The action to be invoked on a successful match

        If any of parameters is :obj:`None`, then the matching against this
        parameter is skipped.
        """
        super().__init__()
        self.fullname = fullname
        self.upper_bound = upper_bound
        self.values = values
        self.default = default
        self.action = action

    def match(self, t: Type) -> Type:
        """
        Match the type variable.

        :param t: The type variable
        :return: :xarg:`t` or a modified copy of :xarg:`t` or a custom type
            based on :xarg:`t` returned by the user-defined action
        :raises .TypeMatchError: on an unsuccessful match
        """
        tt = check(t, TypeVarType)
        if (
            self.fullname is None
            and self.upper_bound is None
            and self.values is None
            and self.default is None
            and self.action is None
        ):
            return tt
        if self.fullname is not None:
            if tt.fullname != self.fullname:
                raise TypeMatchError(f"Full name mismatch")
        upper_bound = (
            self.upper_bound.match(tt.upper_bound)
            if self.upper_bound else tt.upper_bound
        )
        values = self.values.match(tt.values) if self.values else tt.values
        default = (
            self.default.match(tt.default) if self.default else tt.default
        )
        if self.action:
            return self.action(tt, upper_bound, values, default)
        return tt.copy_modified(
            values=values, upper_bound=upper_bound, default=default
        )


class TypeAliasTypePattern(Pattern[Type]):
    """A pattern for :class:`mypy.types.TypeAliasType` types."""

    #: The full name of a type alias
    fullname: str | None
    #: The pattern for the target type of a type alias
    target: Pattern[Type] | None
    #: The pattern for type variables of a type alias
    tvars: Pattern[Sequence[TypeVarLikeType]] | None
    #: The pattern for arguments of a type alias
    args: Pattern[Sequence[Type]] | None
    #: The action to be invoked on a successful match
    action: TypeAliasAction | None

    __slots__ = ("fullname", "target", "tvars", "args", "action")

    def __init__(
        self,
        fullname: str | None = None,
        target: Pattern[Type] | None = None,
        tvars: Pattern[Sequence[TypeVarLikeType]] | None = None,
        args: Pattern[Sequence[Type]] | None = None,
        action: TypeAliasAction | None = None,
    ) -> None:
        """
        Initialize the pattern.

        :param fullname: The full name of a type alias
        :param target: The pattern for the target type of a type alias
        :param tvars: The pattern for type variables of a type alias
        :param args: The pattern for arguments of a type alias
        :param action: The action to be invoked on a successful match

        If any of parameters is :obj:`None`, then the matching against this
        parameter is skipped.
        """
        super().__init__()
        self.fullname = fullname
        self.target = target
        self.tvars = tvars
        self.args = args
        self.action = action

    def match(self, t: Type) -> Type:
        """
        Match the type alias.

        :param t: The type alias
        :return: :xarg:`t` or a modified copy of :xarg:`t` or a custom type
            based on :xarg:`t` returned by the user-defined action
        :raises .TypeMatchError: on an unsuccessful match
        """
        tt = check(t, TypeAliasType)
        if (
            self.fullname is None
            and self.target is None
            and self.tvars is None
            and self.args is None
            and self.action is None
        ):
            return tt
        alias = tt.alias
        if (
            alias is None
            and (
                self.fullname is not None
                or self.target is not None
                or self.tvars is not None
            )
        ):
            raise TypeMatchError("Missing alias")
        if alias:
            if self.fullname is not None:
                if alias.fullname != self.fullname:
                    raise TypeMatchError("Full name mismatch")
            target = (
                self.target.match(alias.target)
                if self.target else alias.target
            )
            tvars = (
                self.tvars.match(alias.alias_tvars)
                if self.tvars else alias.alias_tvars
            )
            if target is not alias.target or tvars is not alias.alias_tvars:
                alias = TypeAlias(
                    target,
                    alias.fullname,
                    alias.module,
                    alias.line,
                    alias.column,
                    alias_tvars=tvars,
                    no_args=alias.no_args,
                    normalized=alias.normalized,
                    eager=alias.eager,
                    python_3_12_type_alias=alias.python_3_12_type_alias,
                )
        args = self.args.match(tt.args) if self.args else tt.args
        if self.action:
            return self.action(tt, alias, args)
        return TypeAliasType(alias, args, tt.line, tt.column)


def object_t(action: InstanceAction | None = None) -> InstancePattern:
    """
    Create a pattern for :class:`object`.

    :param action: The action to be invoked on a successful match
    :return: the pattern for :class:`object`
    """
    return InstancePattern(OBJECT_TYPE, action=action)


def parg(t: Pattern[Type], name: str | None = None) -> Arg:
    """
    Create a pattern for a positional argument.

    :param t: The pattern for the argument type
    :param name: The name of a positional argument
    :return: the pattern for the positional argument
    """
    return Arg(ARG_POS, t, name)


def pargs(t: Pattern[Type], name: str | None = None) -> Arg:
    """
    Create a pattern for positional-only arguments.

    :param t: The pattern for the argument type
    :param name: The name of positional-only arguments
    :return: the pattern for positional-only arguments
    """
    return Arg(ARG_STAR, t, name)


def kargs(t: Pattern[Type], name: str | None = None) -> Arg:
    """
    Create a pattern for key-value-only arguments.

    :param t: The pattern for the argument type
    :param name: The name of key-value-only arguments
    :return: the pattern for key-value-only arguments
    """
    return Arg(ARG_STAR2, t, name)


def callable_t(
    *args: Arg | None,
    ret_type: Pattern[Type] | None = None,
    variables: Pattern[Sequence[TypeVarLikeType]] | None = None,
    action: CallableAction | None = None,
) -> CallableTypePattern:
    """
    Create a pattern for a callable type.

    :param args: The pattern for arguments of a callable type
    :param ret_type: The pattern for the return type of a callable type
    :param variables: The pattern for type variables of a callable type
    :param action: The action to be invoked on a successful match
    :return: the pattern for a callable type
    """
    return CallableTypePattern(
        *args, ret_type=ret_type, variables=variables, action=action
    )


def universal_callable_t(
    action: CallableAction | None = None,
) -> CallableTypePattern:
    """
    Create a pattern for ``Callable[[*object, **object], T]``.

    :param action: The action to be invoked on a successful match
    :return: the pattern for ``Callable[[*object, **object], T]``
    """
    obj_t = object_t()
    return callable_t(pargs(obj_t), kargs(obj_t), action=action)
