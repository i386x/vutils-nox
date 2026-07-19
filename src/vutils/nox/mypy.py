#
# File:    ./src/vutils/nox/mypy.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-06-27 10:33:07 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Mypy plugin that treats :class:`typing.Any` as :class:`object`."""

import contextlib
from collections.abc import Callable, Iterable, Sequence
from typing import Generator, TypeVar

from mypy.checker import TypeChecker
from mypy.nodes import ARG_POS, ARG_STAR, ARG_STAR2, TypeAlias, TypeInfo
from mypy.plugin import (
    AnalyzeTypeContext,
    FunctionContext,
    FunctionSigContext,
    Plugin,
)
from mypy.type_visitor import TypeTranslator
from mypy.typeanal import TypeAnalyser
from mypy.types import (
    AnyType,
    CallableType,
    EllipsisType,
    FunctionLike,
    Instance,
    Parameters,
    ParamSpecFlavor,
    ParamSpecType,
    Type,
    TypeAliasType,
    TypeOfAny,
    TypeVarId,
    TypeVarLikeType,
    TypeVarTupleType,
    TypeVarType,
    get_proper_type,
)

#: Names of special types and functions meaningful only within the context of
#: this plugin
FIX_DECORATOR_FULLNAME = "vutils.nox.utils.fix_decorator_type"

#: Names of some important types
ANY_TYPE = "typing.Any"
CALLABLE_TYPE = "typing.Callable"
DICT_TYPE = "builtins.dict"
FUNCTION_TYPE = "builtins.function"
ITERABLE_TYPE = "typing.Iterable"
OBJECT_TYPE = "builtins.object"
STR_TYPE = "builtins.str"
TUPLE_TYPE = "builtins.tuple"

#: Lists of cases that need to be handled specially by the plugin
COMPARISON_PROTOCOLS = (
    "_typeshed.SupportsDunderLT",
    "_typeshed.SupportsDunderGT",
)
FUNCTIONS_DOING_COMPARISONS = ("builtins.max", "builtins.min")

#: Modes of operation of :class:`.FixSupportsComparison` translator
NORMAL = 0
REPLACE = 1

#: Type variables
_T = TypeVar("_T")


def verify_type(obj: object, typ: type[_T]) -> _T:
    """
    Verify that :xarg:`obj` is an instance of :xarg:`typ`.

    :param obj: The object
    :param typ: The expected type
    :return: the object
    :raises TypeError: when :xarg:`obj` is not an instance of :xarg:`typ`
    """
    if not isinstance(obj, typ):
        raise TypeError(f"Expected an instance of {typ!r}")
    return obj


def new_typevar_id(
    variables: Iterable[TypeVarLikeType] | None, namespace: str
) -> TypeVarId:
    """
    Create a new type variable id.

    :param variables: The list of existing type variables
    :param namespace: The name space under which the new variable id belongs
    :return: the new type variable id
    """
    return TypeVarId(
        -1 if not variables else min(v.id.raw_id for v in variables) - 1,
        namespace=namespace,
    )


def new_paramspec(
    api: TypeChecker,
    name: str,
    tvid: TypeVarId,
) -> ParamSpecType:
    """
    Create a new parameters specification.

    :param api: The type checker instance
    :param name: The parameters specification name
    :param tvid: The type variable id
    :return: the new parameters specification
    """
    return ParamSpecType(
        name,
        f"{api.tscope.current_full_target()}.{name}",
        tvid,
        ParamSpecFlavor.BARE,
        api.named_type(OBJECT_TYPE),
        AnyType(TypeOfAny.from_omitted_generics),
    )


def is_subtype_of(t: TypeInfo, fullname: str) -> bool:
    """
    Test whether :xarg:`fullname` is a subtype of :xarg:`t`.

    :param t: The type
    :param fullname: The subtype's full name
    :return: :obj:`True` if :xarg:`fullname` is a subtype of :xarg:`t`

    The test is based on the MRO of :xarg:`t`.
    """
    return fullname in set(tt.fullname for tt in t.mro)


def can_accept_anything(t: CallableType) -> bool:
    """
    Test whether callable can accept arbitrary arguments.

    :param t: The callable
    :return: :obj:`True` if :xarg:`t` can accept and arbitrary number of
        positional and/or keyword arguments of an arbitrary type
    """
    return (
        len(t.arg_types) == 2
        and t.arg_kinds == [ARG_STAR, ARG_STAR2]
        and isinstance(t.arg_types[0], Instance)
        and t.arg_types[0].type.fullname == OBJECT_TYPE
        and isinstance(t.arg_types[1], Instance)
        and t.arg_types[1].type.fullname == OBJECT_TYPE
    )


class FixSupportsComparison(TypeTranslator):
    """
    Translate :class:`object` in comparison protocols to the given type.

    Translate :class:`object` in :class:`_typeshed.SupportsDunderLT` and
    :class:`_typeshed.SupportsDunderGT` argument to the given type.
    """

    #: The new type that will replace :class:`object`
    new_type: Type
    #: The mode of operation
    mode: int

    __slots__ = ("new_type", "mode")

    def __init__(self, new_type: Type) -> None:
        """
        Initialize the translator.

        :param new_type: The new type that will replace :class:`object` during
            the translation
        """
        self.new_type = new_type
        self.mode = NORMAL
        super().__init__()

    @contextlib.contextmanager
    def set_mode(self, mode: int) -> Generator[None, None, None]:
        """
        Create a new mode of operation context.

        :param mode: The new mode of operation
        :return: the generator managing the context
        """
        old_mode = self.mode
        try:
            self.mode = mode
            yield
        finally:
            self.mode = old_mode

    def visit_instance(self, t: Instance, /) -> Type:
        """
        Translate :class:`mypy.types.Instance` type.

        :param t: The :class:`mypy.types.Instance` type
        :return: the translated :class:`mypy.types.Instance` type
        """
        if t.type.fullname == OBJECT_TYPE and self.mode == REPLACE:
            return self.new_type
        mode = NORMAL
        if (
            t.type.fullname in COMPARISON_PROTOCOLS
            and len(t.args) == 1
            and isinstance(t.args[0], Instance)
            and t.args[0].type.fullname == OBJECT_TYPE
        ):
            mode = REPLACE
        with self.set_mode(mode):
            return super().visit_instance(t)

    def visit_type_var(self, t: TypeVarType, /) -> Type:
        """
        Translate :class:`mypy.types.TypeVarType` type.

        :param t: The :class:`mypy.types.TypeVarType` type
        :return: the translated :class:`mypy.types.TypeVarType` type
        """
        return t.copy_modified(
            values=self.translate_type_list(t.values),
            upper_bound=t.upper_bound.accept(self),
            default=t.default.accept(self),
        )

    def visit_param_spec(self, t: ParamSpecType, /) -> Type:
        """
        Translate :class:`mypy.types.ParamSpecType` type.

        :param t: The :class:`mypy.types.ParamSpecType` type
        :return: the translated :class:`mypy.types.ParamSpecType` type
        :raises TypeError: when a type translation fails
        """
        return ParamSpecType(
            t.name,
            t.fullname,
            t.id,
            t.flavor,
            t.upper_bound.accept(self),
            default=t.default.accept(self),
            line=t.line,
            column=t.column,
            prefix=verify_type(t.prefix.accept(self), Parameters),
        )

    def visit_parameters(self, t: Parameters, /) -> Type:
        """
        Translate :class:`mypy.types.Parameters` type.

        :param t: The :class:`mypy.types.Parameters` type
        :return: the translated :class:`mypy.types.Parameters` type
        """
        return t.copy_modified(
            arg_types=self.translate_type_list(t.arg_types),
            variables=self.translate_type_list(list(t.variables)),
        )

    def visit_type_var_tuple(self, t: TypeVarTupleType, /) -> Type:
        """
        Translate :class:`mypy.types.TypeVarTupleType` type.

        :param t: The :class:`mypy.types.TypeVarTupleType` type
        :return: the translated :class:`mypy.types.TypeVarTupleType` type
        """
        return t.copy_modified(
            upper_bound=t.upper_bound.accept(self),
            default=t.default.accept(self),
        )

    def translate_variables(
        self, variables: Sequence[TypeVarLikeType]
    ) -> Sequence[TypeVarLikeType]:
        """
        Translate type variables.

        :param variables: The list of type variables
        :return: the list of translated type variables
        :raises TypeError: when a type translation fails
        """
        return [
            verify_type(v.accept(self), TypeVarLikeType) for v in variables
        ]

    def visit_type_alias_type(self, t: TypeAliasType, /) -> Type:
        """
        Translate :class:`mypy.types.TypeAliasType` type.

        :param t: The :class:`mypy.types.TypeAliasType` type
        :return: the translated :class:`mypy.types.TypeAliasType` type
        """
        alias = (
            TypeAlias(
                t.alias.target.accept(self),
                t.alias.fullname,
                t.alias.module,
                t.alias.line,
                t.alias.column,
                alias_tvars=list(
                    self.translate_variables(t.alias.alias_tvars)
                ),
                no_args=t.alias.no_args,
                normalized=t.alias.normalized,
                eager=t.alias.eager,
                python_3_12_type_alias=t.alias.python_3_12_type_alias,
            )
            if t.alias
            else None
        )
        return TypeAliasType(
            alias,
            self.translate_type_list(t.args),
            t.line,
            t.column,
        )


def make_object(ctx: AnalyzeTypeContext) -> Type:
    """
    Make an :class:`object` type based on the context.

    :param ctx: The type analyzer context
    :return: the :class:`object` type
    :raises TypeError: when :xarg:`ctx.api` is not an instance of
        :class:`mypy.typeanal.TypeAnalyser`
    """
    t = ctx.type
    api = verify_type(ctx.api, TypeAnalyser)
    return api.named_type(OBJECT_TYPE, line=t.line, column=t.column)


def make_universal_callable(
    ctx: AnalyzeTypeContext,
    ret_type: Type | None = None,
    with_location: bool = True,
) -> Type:
    """
    Make a ``Callable[[*object, **object], T]`` type.

    :param ctx: The type analyzer context
    :param ret_type: The return type of the returned callable type
    :param with_location: The flag indicating whether line and column from the
        context should be part of the returned callable type
    :return: the new callable type
    :raises TypeError: when :xarg:`ctx.api` is not an instance of
        :class:`mypy.typeanal.TypeAnalyser`

    If :xarg:`ret_type` is :obj:`None`, make
    ``Callable[[*object, **object], object]`` type. Otherwise, make
    ``Callable[[*object, **object], ret_type]`` type.
    """
    api = verify_type(ctx.api, TypeAnalyser)
    object_type = (
        make_object(ctx) if with_location else api.named_type(OBJECT_TYPE)
    )
    return CallableType(
        [object_type, object_type],
        [ARG_STAR, ARG_STAR2],
        [None, None],
        ret_type=object_type if ret_type is None else ret_type,
        fallback=api.named_type(FUNCTION_TYPE),
        is_ellipsis_args=False,
    ).accept(api)


def handle_unspecified_parameters_in_callable(ctx: AnalyzeTypeContext) -> Type:
    """
    Handle bare :class:`typing.Callable` and ``Callable[..., T]``.

    :param ctx: The type analyzer context
    :return: the sanitized :class:`typing.Callable`
    :raises TypeError: when :xarg:`ctx.api` is not an instance of
        :class:`mypy.typeanal.TypeAnalyser`

    These forms of :class:`typing.Callable`s contain :class:`typing.Any` so
    they are converted to ``Callable[[*object, **object], T]`` before ``mypy``
    takes care of them. Unfortunately, this may cause new kinds of problems,
    like type incompatibility caused by changed variance. Such cases must be
    handled further in followup hooks.
    """
    t = ctx.type
    api = verify_type(ctx.api, TypeAnalyser)

    # Treat special cases before they hit `api.analyze_callable_type(t)`
    if len(t.args) == 0:
        return make_universal_callable(ctx)
    if len(t.args) == 2:
        callable_args = t.args[0]
        ret_type = t.args[1]
        if isinstance(callable_args, EllipsisType):
            return make_universal_callable(ctx, ret_type, with_location=False)
    # Fallback the rest of cases to the `mypy` internal logic
    return api.analyze_callable_type(t)


def adjust_supports_comparison(ctx: FunctionSigContext) -> FunctionLike:
    """
    Adjust a function accepting arguments implementing a comparison protocol.

    :param ctx: The function signature context
    :return: the adjusted function signature
    :raises TypeError: when the adjusted function signature is not an instance
        of :class:`mypy.types.CallableType`

    If a function signature contains ``_typeshed.SupportsDunderLT[object]`` or
    ``_typeshed.SupportsDunderGT[object]`` then replace ``object`` with the
    type deduced from the first passed positional argument. If that argument is
    iterable, use the underlying type (the type of iterable's elements).
    """
    args = ctx.args
    sig = ctx.default_signature
    api = ctx.api
    if len(args) == 0 or len(args[0]) == 0:
        return sig
    tt = get_proper_type(api.get_expression_type(args[0][0]))
    # Covers also the `Generator[T, None, None]` case
    if isinstance(tt, Instance) and is_subtype_of(tt.type, ITERABLE_TYPE):
        tt = get_proper_type(tt.args[0])
    return verify_type(sig.accept(FixSupportsComparison(tt)), CallableType)


def adjust_universal_callable_in_decorator(ctx: FunctionContext) -> Type:
    """
    Adjust ``Callable[[*object, **object], T]`` to ``Callable[P, T]``.

    :param ctx: The function context
    :return: the adjusted return type for the analyzed function that triggered
        this hook function
    :raises TypeError: when :xarg:`ctx.api` is not an instance of
        :class:`mypy.checker.TypeChecker`

    Use this function as a hook to adjust a decorator signature, e.g. in a
    context like ::

        @our_deco(their_deco)
        def our_function():
            ...

    where ``our_deco`` is an identity function triggering this hook function
    (``mypy`` does not call ``get_function_signature_hook`` on decorators).
    This ensures that ``their_deco`` signature can be accessed via
    :xarg:`ctx.default_return_type`.

    First, check if ``their_deco`` has a signature of the form
    ``Callable[[C], T]``, where ``C`` is a callable. If not, then tell ``mypy``
    to fail.

    Second, if ``C`` is of the form ``Callable[[*object, **object], U]``,
    replace it with ``Callable[P, U]``, where ``P`` is newly introduced
    parameter specification, roughly equal to ``typing.ParamSpec("P")``, not
    conflicting with other type variables.
    """
    emsg_deco = f"{FIX_DECORATOR_FULLNAME} must be used on a decorator"
    nmsg_redu = f"{FIX_DECORATOR_FULLNAME} is redundant at this place"
    api = verify_type(ctx.api, TypeChecker)
    typ = ctx.default_return_type
    if not isinstance(typ, CallableType):
        api.fail(emsg_deco, ctx.context)
        return typ
    if (
        len(typ.arg_types) != 1
        or not isinstance(typ.arg_types[0], CallableType)
        or typ.arg_kinds != [ARG_POS]
    ):
        api.fail(emsg_deco, ctx.context)
        return typ
    arg_typ = typ.arg_types[0]
    if not can_accept_anything(arg_typ):
        api.note(nmsg_redu, ctx.context)
        return typ
    tvid = new_typevar_id(typ.variables, FIX_DECORATOR_FULLNAME)
    p_bare = new_paramspec(api, "P", tvid)
    p_args = p_bare.with_flavor(ParamSpecFlavor.ARGS)
    p_args.upper_bound = api.named_generic_type(
        TUPLE_TYPE, [api.named_type(OBJECT_TYPE)]
    )
    p_kwargs = p_bare.with_flavor(ParamSpecFlavor.KWARGS)
    p_kwargs.upper_bound = api.named_generic_type(
        DICT_TYPE, [api.named_type(STR_TYPE), api.named_type(OBJECT_TYPE)]
    )
    variables = (p_bare,) + typ.variables
    return typ.copy_modified(
        arg_types=[arg_typ.copy_modified(arg_types=[p_args, p_kwargs])],
        variables=variables,
    )


class TranslateEmailHeaderDecodeHeaderRt:
    """"""

    __slots__ = ()

    def __init__(self) -> None:
        """"""
        self.state = EXPECT_LIST

def adjust_email_header_decode_header_rt(ctx: FunctionContext) -> Type:
    """
    Adjust :func:`email.header.decode_header` return type.

    :param ctx: The function context
    :return: the adjusted return type of :func:`email.header.decode_header`

    The original return type of :func:`email.header.decode_header` is
    ``list[tuple[Any, Any | None]]``, which after replacing :class:`typing.Any`
    with :class:`object` becomes ``list[tuple[object, object | None]]``.
    According to the semantics of :func:`email.header.decode_header`, the
    correct return type is ``list[tuple[str | bytes, str | None]]``.
    """
    api = verify_type(ctx.api, TypeChecker)
    rt = ctx.default_return_type
    if not isinstance(rt, Instance) or rt.type.fullname != LIST_TYPE:
        return rt
    if len(rt.args) != 1:
        return rt
    return rt.copy_modified(args=[])

    tt = rt.args[0]
    if not isinstance(tt, Instance) or tt.type.fullname != TUPLE_TYPE:
        return rt
    if len(tt.args) != 2:
        return rt
    ttx = tt.args[0]
    if not isinstance(ttx, Instance) or ttx.type.fullname != OBJECT_TYPE:
        return rt
    tty = tt.args[1]
    if not isinstance(tty, UnionType):
        return rt
    if len(tty.items) != 2:
        return rt


class LiftAnyPlugin(Plugin):
    """Replace any occurrence of :class:`typing.Any` with :class:`object`."""

    __slots__ = ()

    def get_type_analyze_hook(
        self, fullname: str
    ) -> Callable[[AnalyzeTypeContext], Type] | None:
        """
        Return a hook called when a type is met.

        :param fullname: The fully qualified name of the type being analyzed
        :return: the hook called when a type is met
        """
        if fullname == ANY_TYPE:
            return make_object
        if fullname == CALLABLE_TYPE:
            return handle_unspecified_parameters_in_callable
        return None

    def get_function_signature_hook(
        self, fullname: str
    ) -> Callable[[FunctionSigContext], FunctionLike] | None:
        """
        Return a hook called when a function signature is checked.

        :param fullname: The fully qualified name of the function being
            analyzed
        :return: the hook called when a function signature is met
        """
        if fullname in FUNCTIONS_DOING_COMPARISONS:
            return adjust_supports_comparison
        return None

    def get_function_hook(
        self, fullname: str
    ) -> Callable[[FunctionContext], Type] | None:
        """
        Return a hook called to adjust a function's return type.

        :param fullname: The fully qualified name of the function being
            analyzed
        :return: the hook that is called to do possible adjustments to the
            function's return type
        """
        if fullname == FIX_DECORATOR_FULLNAME:
            return adjust_universal_callable_in_decorator
        return None


def plugin(unused_version: str) -> type[Plugin]:
    """
    Return the plugin.

    :param unused_version: The version of ``mypy``
    :return: the plugin
    """
    return LiftAnyPlugin
