#
# File:    ./src/vutils/nox/mypy/liftany.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-08-09 07:37:33 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Plugin that lifts any use of :class:`typing.Any`."""

from collections.abc import Sequence

from mypy.checker import TypeChecker
from mypy.plugin import FunctionContext
from mypy.types import CallableType, Type, TypeVarLikeType

from vutils.nox.mypy.tpatt import callable_t, parg, universal_callable_t
from vutils.nox.mypy.transforms import CaptureType
from vutils.nox.mypy.utils import (
    FIX_DECORATOR_TYPE_FUNC,
    ParamSpecFactory,
    verify_type,
)


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
