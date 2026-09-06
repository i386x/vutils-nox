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
from collections.abc import Sequence

from mypy.checker import TypeChecker
from mypy.plugin import FunctionContext
from mypy.types import CallableType, Type, TypeVarLikeType

from vutils.nox.mypy.tpatt import (
    Arg,
    CallableTypePattern,
    InstanceAction,
    InstancePattern,
    Seq,
    TypeAliasTypePattern,
    TypeVarTypePattern,
    callable_t,
    instance_t,
    none_t,
    object_t,
    parg,
    type_alias,
    typevar_t,
    universal_callable_t,
)
from vutils.nox.mypy.transforms import CaptureType
from vutils.nox.mypy.utils import (
    FIX_DECORATOR_TYPE_FUNC,
    ParamSpecFactory,
    verify_type,
)

#: Names of type variables
SUPPORTS_RICH_COMPARISON_TV = "_typeshed.SupportsRichComparisonT"

#: Names of type aliases
SUPPORTS_RICH_COMPARISON_TA = "_typeshed.SupportsRichComparison"

#: Names of protocols
SUPPORTS_DUNDER_GT_PROTO = "_typeshed.SupportsDunderGT"
SUPPORTS_DUNDER_LT_PROTO = "_typeshed.SupportsDunderLT"

#: Names of functions or regular expressions matching them
BUILTINS_MIN_MAX_RE = re.compile(r"^builtins\.(?:min|max)#(\d+)$")


def supports_dunder_lt(
    action: InstanceAction | None = None
) -> InstancePattern:
    """
    Create a pattern for ``_typeshed.SupportsDunderLT[object]``.

    :param action: The action to be invoked on a successful match
    :return: the pattern for ``_typeshed.SupportsDunderLT[object]``
    """
    return instance_t(SUPPORTS_DUNDER_LT_PROTO, object_t(), action=action)


def supports_dunder_gt(
    action: InstanceAction | None = None
) -> InstancePattern:
    """
    Create a pattern for ``_typeshed.SupportsDunderGT[object]``.

    :param action: The action to be invoked on a successful match
    :return: the pattern for ``_typeshed.SupportsDunderGT[object]``
    """
    return instance_t(SUPPORTS_DUNDER_GT_PROTO, object_t(), action=action)


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
        arg, arg, arg, Arg(none_t()), return_type=tv, variables=Seq([tv])
    )


def get_min_max_sig_pattern(
    sig: CallableType
) -> Callable[[InstanceAction | None], CallableTypePattern] | None:
    """
    """
    if len(sig.arg_types) == 0:
        return None
    arg0_t = sig.arg_types[0]
    if isinstance(arg0_t, Instance) and len(arg0_t.args) > 0:
        arg0_t = arg0_t.args[0]
    namespace = arg0_t.id.namespace if isinstance(arg0_t, TypeVarType) else ""
    m = BUILTINS_MIN_MAX_RE.match(namespace)
    if m is None:
        return None
    fnum = int(m.group(1))
    if fnum == 0:
        return min_max_sig_0
    return None


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
    sig_tf = get_min_max_sig_pattern(sig)
    if sig_tf is None:
        return sig
    result = sig_tf(Replace(tt)).try_match(sig)
    if isinstance(result, TypeError):
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
