#
# File:    ./src/vutils/nox/mypy/liftany.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-08-09 07:37:33 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Plugin that lifts any use of :class:`typing.Any`."""

import functools
import re
from collections.abc import Sequence
from typing import Callable

from mypy.checker import TypeChecker
from mypy.nodes import ARG_STAR, ARG_STAR2
from mypy.plugin import (
    AnalyzeTypeContext,
    FunctionContext,
    FunctionSigContext,
    Plugin,
)
from mypy.typeanal import TypeAnalyser
from mypy.types import (
    CallableType,
    EllipsisType,
    FunctionLike,
    Instance,
    LiteralType,
    Type,
    TypeVarLikeType,
    TypeVarType,
    UnionType,
    get_proper_type,
)

from vutils.nox.mypy.tpatt import (
    Arg,
    CallableTypePattern,
    InstanceAction,
    InstancePattern,
    Seq,
    TypeAliasTypePattern,
    TypeMatchError,
    TypeVarTypePattern,
    callable_t,
    instance_t,
    list_t,
    none_t,
    object_t,
    parg,
    tuple_t,
    type_alias,
    typevar_t,
    universal_callable_t,
)
from vutils.nox.mypy.transforms import CaptureType, ModifyInstance
from vutils.nox.mypy.utils import (
    ANY_TYPE,
    BYTES_TYPE,
    CALLABLE_TYPE,
    FIX_DECORATOR_TYPE_FUNC,
    ITERABLE_TYPE,
    OBJECT_TYPE,
    STR_TYPE,
    ParamSpecFactory,
    is_subtype_of,
    new_object,
    verify_type,
)

#: Names of type variables
BUILTINS_T_TV = "builtins._T"
BUILTINS_T1_TV = "builtins._T1"
BUILTINS_T2_TV = "builtins._T2"
SUPPORTS_RICH_COMPARISON_TV = "_typeshed.SupportsRichComparisonT"

#: Names of type aliases
SUPPORTS_RICH_COMPARISON_TA = "_typeshed.SupportsRichComparison"

#: Names of protocols
SUPPORTS_DUNDER_GT_PROTO = "_typeshed.SupportsDunderGT"
SUPPORTS_DUNDER_LT_PROTO = "_typeshed.SupportsDunderLT"

#: Names of functions or regular expressions matching them
BUILTINS_MAX = "builtins.max"
BUILTINS_MIN = "builtins.min"
BUILTINS_MIN_MAX_RE = re.compile(r"^builtins\.(?:min|max)(#\d+)?$")
EMAIL_HEADER_DECODE_HEADER = "email.header.decode_header"


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
        new_object(ctx) if with_location else api.named_type(OBJECT_TYPE)
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
    they are converted to ``Callable[[*object, **object], T]`` before mypy
    takes care of them. Unfortunately, this may cause new kinds of problems,
    like type incompatibility caused by changed variance. Such cases must be
    handled further in the followup hooks.
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
    # Fallback the rest of cases to the mypy internal logic
    return api.analyze_callable_type(t)


@functools.cache
def supports_dunder_lt(
    action: InstanceAction | None = None
) -> InstancePattern:
    """
    Create a pattern for ``_typeshed.SupportsDunderLT[object]``.

    :param action: The action to be invoked on a successful match
    :return: the pattern for ``_typeshed.SupportsDunderLT[object]``
    """
    return instance_t(SUPPORTS_DUNDER_LT_PROTO, object_t(), action=action)


@functools.cache
def supports_dunder_gt(
    action: InstanceAction | None = None
) -> InstancePattern:
    """
    Create a pattern for ``_typeshed.SupportsDunderGT[object]``.

    :param action: The action to be invoked on a successful match
    :return: the pattern for ``_typeshed.SupportsDunderGT[object]``
    """
    return instance_t(SUPPORTS_DUNDER_GT_PROTO, object_t(), action=action)


@functools.cache
def supports_rich_comparison(
    action: InstanceAction | None = None
) -> TypeAliasTypePattern:
    """
    Create a pattern for ``_typeshed.SupportsRichComparison``.

    :param action: The action to be invoked on a successful match
    :return: the pattern for ``_typeshed.SupportsRichComparison``
    """
    return type_alias(
        SUPPORTS_RICH_COMPARISON_TA,
        supports_dunder_lt(action) | supports_dunder_gt(action),
    )


@functools.cache
def supports_rich_comparison_t(
    action: InstanceAction | None = None
) -> TypeVarTypePattern:
    """
    Create a pattern for ``_typeshed.SupportsRichComparisonT``.

    :param action: The action to be invoked on a successful match
    :return: the pattern for ``_typeshed.SupportsRichComparisonT``
    """
    return typevar_t(
        SUPPORTS_RICH_COMPARISON_TV, supports_rich_comparison(action)
    )


def min_max_sig_0(action: InstanceAction | None = None) -> CallableTypePattern:
    """
    Create a pattern for :func:`min` and :func:`max` signatures.

    :param action: The action to be invoked on a successful match
    :return: the pattern for :func:`min` and :func:`max` 0th variant signatures

    Create a pattern that matches ``def func(arg1: SupportsRichComparisonT,
    arg2: SupportsRichComparisonT, /, *_args: SupportsRichComparisonT,
    key: None = None) -> SupportsRichComparisonT: ...``.
    """
    tv = supports_rich_comparison_t(action)
    arg = Arg(tv)
    return callable_t(
        arg, arg, arg, Arg(none_t()), ret_type=tv, variables=Seq([tv])
    )


def min_max_sig_1(action: InstanceAction | None = None) -> CallableTypePattern:
    """
    Create a pattern for :func:`min` and :func:`max` signatures.

    :param action: The action to be invoked on a successful match
    :return: the pattern for :func:`min` and :func:`max` 1st variant signatures

    Create a pattern that matches ``def func(arg1: _T, arg2: _T, /, *_args: _T,
    key: Callable[[_T], SupportsRichComparison]) -> _T: ...``.
    """
    tv = typevar_t(BUILTINS_T_TV, object_t())
    ta = supports_rich_comparison(action)
    arg = Arg(tv)
    return callable_t(
        arg,
        arg,
        arg,
        Arg(callable_t(arg, ret_type=ta)),
        ret_type=tv,
        variables=Seq([tv]),
    )


def min_max_sig_2(action: InstanceAction | None = None) -> CallableTypePattern:
    """
    Create a pattern for :func:`min` and :func:`max` signatures.

    :param action: The action to be invoked on a successful match
    :return: the pattern for :func:`min` and :func:`max` 2nd variant signatures

    Create a pattern that matches ``def func(iterable:
    Iterable[SupportsRichComparisonT], /, *, key: None = None) ->
    SupportsRichComparisonT: ...``.
    """
    tv = supports_rich_comparison_t(action)
    return callable_t(
        Arg(instance_t(ITERABLE_TYPE, tv)),
        Arg(none_t()),
        ret_type=tv,
        variables=Seq([tv]),
    )


def min_max_sig_3(action: InstanceAction | None = None) -> CallableTypePattern:
    """
    Create a pattern for :func:`min` and :func:`max` signatures.

    :param action: The action to be invoked on a successful match
    :return: the pattern for :func:`min` and :func:`max` 3rd variant signatures

    Create a pattern that matches ``def func(iterable: Iterable[_T], /, *, key:
    Callable[[_T], SupportsRichComparison]) -> _T: ...``.
    """
    tv = typevar_t(BUILTINS_T_TV, object_t())
    return callable_t(
        Arg(instance_t(ITERABLE_TYPE, tv)),
        Arg(callable_t(Arg(tv), ret_type=supports_rich_comparison(action))),
        ret_type=tv,
        variables=Seq([tv]),
    )


def min_max_sig_4(action: InstanceAction | None = None) -> CallableTypePattern:
    """
    Create a pattern for :func:`min` and :func:`max` signatures.

    :param action: The action to be invoked on a successful match
    :return: the pattern for :func:`min` and :func:`max` 4th variant signatures

    Create a pattern that matches ``def func(iterable:
    Iterable[SupportsRichComparisonT], /, *, key: None = None, default: _T) ->
    SupportsRichComparisonT | _T: ...``.
    """
    tv1 = supports_rich_comparison_t(action)
    tv2 = typevar_t(BUILTINS_T_TV, object_t())
    return callable_t(
        Arg(instance_t(ITERABLE_TYPE, tv1)),
        Arg(none_t()),
        Arg(tv2),
        ret_type=tv1 | tv2,
        variables=Seq([tv1, tv2]),
    )


def min_max_sig_5(action: InstanceAction | None = None) -> CallableTypePattern:
    """
    Create a pattern for :func:`min` and :func:`max` signatures.

    :param action: The action to be invoked on a successful match
    :return: the pattern for :func:`min` and :func:`max` 5th variant signatures

    Create a pattern that matches ``def func(iterable: Iterable[_T1], /, *,
    key: Callable[[_T1], SupportsRichComparison], default: _T2) -> _T1 | _T2:
    ...``.
    """
    tv1 = typevar_t(BUILTINS_T1_TV, object_t())
    tv2 = typevar_t(BUILTINS_T2_TV, object_t())
    return callable_t(
        Arg(instance_t(ITERABLE_TYPE, tv1)),
        Arg(callable_t(tv1, ret_type=supports_rich_comparison(action))),
        Arg(tv2),
        ret_type=tv1 | tv2,
        variables=Seq([tv1, tv2]),
    )


def get_min_max_sig_pattern_factory(
    sig: CallableType
) -> Callable[[InstanceAction | None], CallableTypePattern] | None:
    """
    Get the right type pattern factory for :func:`min` and :func:`max`.

    :param sig: The signature of :func:`min` or :func:`max`
    :return: the type pattern factory that creates a pattern for matching the
        :func:`min` or :func:`max` signature or :obj:`None` if there is no such
        a factory
    """
    if len(sig.arg_types) == 0:
        return None
    arg0_t = sig.arg_types[0]
    if isinstance(arg0_t, Instance) and len(arg0_t.args) > 0:
        arg0_t = arg0_t.args[0]
    namespace = arg0_t.id.namespace if isinstance(arg0_t, TypeVarType) else ""
    m = BUILTINS_MIN_MAX_RE.match(namespace)
    return {
        "#0": min_max_sig_0,
        "#1": min_max_sig_1,
        "#2": min_max_sig_2,
        "#3": min_max_sig_3,
        "#4": min_max_sig_4,
        "##": min_max_sig_5,
    }.get(m and (m.group(1) or "##"))


def adjust_builtins_min_max(ctx: FunctionSigContext) -> FunctionLike:
    """
    Adjust signatures of :func:`min` and :func:`max`.

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
    sig_pf = get_min_max_sig_pattern_factory(sig)
    if sig_pf is None:
        return sig
    result = sig_pf(ModifyInstance([tt])).try_match(sig)
    if isinstance(result, TypeMatchError):
        return sig
    return verify_type(result, CallableType)


def adjust_universal_callable_in_decorator(ctx: FunctionContext) -> Type:
    """
    Adjust ``Callable[[*object, **object], T]`` to ``Callable[P, T]``.

    :param ctx: The function context
    :return: the adjusted return type for the analyzed function that triggered
        this hook function
    :raises TypeError: when :xarg:`ctx.api` is not an instance of
        :class:`mypy.checker.TypeChecker` or a pattern over a type is
        ill-formed

    Use this function as a hook to adjust a decorator signature, e.g. in a
    context like ::

        @our_deco(their_deco)
        def our_function():
            ...

    where ``our_deco`` is an identity function triggering this hook function
    (mypy does not call ``get_function_signature_hook`` on decorators). This
    ensures that ``their_deco`` signature can be accessed via
    :xarg:`ctx.default_return_type`.

    First, check if ``their_deco`` has a signature of the form
    ``Callable[[C], T]``, where ``C`` is a callable. If not, then tell mypy to
    fail.

    Second, if ``C`` is of the form ``Callable[[*object, **object], U]``,
    replace it with ``Callable[P, U]``, where ``P`` is newly introduced
    parameter specification, roughly equal to ``typing.ParamSpec("P")``, not
    conflicting with other type variables.
    """
    outer_capt: CaptureType[
        CallableType, Sequence[Type], Type, Sequence[TypeVarLikeType]
    ] = CaptureType()
    inner_capt: CaptureType[
        CallableType, Sequence[Type], Type, Sequence[TypeVarLikeType]
    ] = CaptureType()
    emsg_deco = f"{FIX_DECORATOR_TYPE_FUNC} must be used on a decorator"
    nmsg_redu = f"{FIX_DECORATOR_TYPE_FUNC} is redundant at this place"
    api = verify_type(ctx.api, TypeChecker)
    typ = ctx.default_return_type

    if not callable_t(
        parg(callable_t(None, action=inner_capt)), action=outer_capt
    ).test(typ):
        api.fail(emsg_deco, ctx.context)
        return typ

    inner = inner_capt.get()
    if not universal_callable_t().test(inner):
        api.note(nmsg_redu, ctx.context)
        return typ

    outer = outer_capt.get()
    psfac = ParamSpecFactory(api, FIX_DECORATOR_TYPE_FUNC, outer.variables)
    pspec = psfac.get("P")

    return outer.copy_modified(
        arg_types=[inner.copy_modified(arg_types=[pspec.args, pspec.kwargs])],
        variables=psfac.variables,
    )


def adjust_return_email_header_decode_header(ctx: FunctionContext) -> Type:
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

    def to_str_or_bytes(
        t: Instance,
        unused_args: Sequence[Type],
        unused_last_known_value: LiteralType | None,
    ) -> Type:
        """
        Replace :xarg:`t` with ``str | bytes``.

        :param t: The instance type
        :param unused_args: The instance type arguments
        :param unused_last_known_value: The instance type *last known value*
        :return: the ``str | bytes`` type
        """
        return UnionType(
            [api.named_type(STR_TYPE), api.named_type(BYTES_TYPE)],
            line=t.line,
            column=t.column,
        )

    def to_str(
        unused_t: Instance,
        unused_args: Sequence[Type],
        unused_last_known_value: LiteralType | None,
    ) -> Type:
        """
        Replace :xarg:`unused_t` with :class:`str`.

        :param unused_t: The instance type
        :param unused_args: The instance type arguments
        :param unused_last_known_value: The instance type *last known value*
        :return: the :class:`str` type
        """
        return api.named_type(STR_TYPE)

    result = list_t(
        tuple_t(object_t(to_str_or_bytes), object_t(to_str) | none_t())
    ).try_match(rt)
    if isinstance(result, TypeMatchError):
        return rt
    return result


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
        return {
            ANY_TYPE: new_object,
            CALLABLE_TYPE: handle_unspecified_parameters_in_callable,
        }.get(fullname)

    def get_function_signature_hook(
        self, fullname: str
    ) -> Callable[[FunctionSigContext], FunctionLike] | None:
        """
        Return a hook called when a function signature is checked.

        :param fullname: The fully qualified name of the function being
            analyzed
        :return: the hook called when a function signature is met
        """
        return {
            BUILTINS_MIN: adjust_builtins_min_max,
            BUILTINS_MAX: adjust_builtins_min_max,
        }.get(fullname)

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
        return {
            FIX_DECORATOR_TYPE_FUNC: adjust_universal_callable_in_decorator,
            EMAIL_HEADER_DECODE_HEADER: adjust_return_email_header_decode_header,
        }.get(fullname)


def plugin(unused_version: str) -> type[Plugin]:
    """
    Return the plugin.

    :param unused_version: The version of mypy
    :return: the plugin
    """
    return LiftAnyPlugin
