#
# File:    ./src/vutils/nox/mypy.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-06-27 10:33:07 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Mypy plugin."""

import contextlib
from collections.abc import Callable, Iterable, Sequence
from typing import Generator

from mypy.checker import TypeChecker
from mypy.nodes import ARG_POS, ARG_STAR, ARG_STAR2, TypeAlias, TypeInfo
from mypy.plugin import (
    AnalyzeTypeContext,
    FunctionContext,
    FunctionSigContext,
    Plugin,
)
from mypy.type_visitor import TypeTranslator
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

COMPARISON_PROTOCOLS = (
    "_typeshed.SupportsDunderLT",
    "_typeshed.SupportsDunderGT",
)
FUNCTIONS_ACCEPTING_COMPARISON_PROTOCOLS = ("builtins.max", "builtins.min")
NORMAL = 0
REPLACE = 1


def new_typevar_id(
    variables: Iterable[TypeVarLikeType] | None, namespace: str
) -> TypeVarId:
    return TypeVarId(
        -1 if not variables else min(v.id.raw_id for v in variables) - 1,
        namespace=namespace,
    )


def new_paramspec(
    api: TypeChecker,
    name: str,
    tvid: TypeVarId,
) -> ParamSpecType:
    return ParamSpecType(
        name,
        f"{api.tscope.current_full_target()}.{name}",
        tvid,
        ParamSpecFlavor.BARE,
        api.named_type("builtins.object"),
        AnyType(TypeOfAny.from_omitted_generics),
    )


def is_subtype(t: TypeInfo, fullname: str) -> bool:
    return fullname in set(tt.fullname for tt in t.mro)


def can_accept_anything(t: CallableType) -> bool:
    return (
        len(t.arg_types) == 2
        and t.arg_kinds == [ARG_STAR, ARG_STAR2]
        and isinstance(t.arg_types[0], Instance)
        and t.arg_types[0].type.fullname == "builtins.object"
        and isinstance(t.arg_types[1], Instance)
        and t.arg_types[1].type.fullname == "builtins.object"
    )


class FixSupportsComparison(TypeTranslator):
    new_type: Type
    mode: int

    def __init__(self, new_type: Type) -> None:
        self.new_type = new_type
        self.mode = NORMAL
        super().__init__()

    @contextlib.contextmanager
    def set_mode(self, mode: int) -> Generator[None, None, None]:
        old_mode = self.mode
        try:
            self.mode = mode
            yield
        finally:
            self.mode = old_mode

    def visit_instance(self, t: Instance, /) -> Type:
        if t.type.fullname == "builtins.object" and self.mode == REPLACE:
            return self.new_type
        mode = NORMAL
        if (
            t.type.fullname in COMPARISON_PROTOCOLS
            and len(t.args) == 1
            and isinstance(t.args[0], Instance)
            and t.args[0].type.fullname == "builtins.object"
        ):
            mode = REPLACE
        with self.set_mode(mode):
            return super().visit_instance(t)

    def visit_type_var(self, t: TypeVarType, /) -> Type:
        return t.copy_modified(
            values=self.translate_type_list(t.values),
            upper_bound=t.upper_bound.accept(self),
            default=t.default.accept(self),
        )

    def visit_param_spec(self, t: ParamSpecType, /) -> Type:
        return ParamSpecType(
            t.name,
            t.fullname,
            t.id,
            t.flavor,
            t.upper_bound.accept(self),
            default=t.default.accept(self),
            line=t.line,
            column=t.column,
            prefix=t.prefix.accept(self),
        )

    def visit_parameters(self, t: Parameters, /) -> Type:
        return t.copy_modified(
            arg_types=self.translate_type_list(t.arg_types),
            variables=self.translate_type_list(t.variables),
        )

    def visit_type_var_tuple(self, t: TypeVarTupleType, /) -> Type:
        return t.copy_modified(
            upper_bound=t.upper_bound.accept(self),
            default=t.default.accept(self),
        )

    def translate_variables(
        self, variables: Sequence[TypeVarLikeType]
    ) -> Sequence[TypeVarLikeType]:
        return type(variables)(v.accept(self) for v in variables)

    def visit_type_alias_type(self, t: TypeAliasType, /) -> Type:
        alias = (
            TypeAlias(
                t.alias.target.accept(self),
                t.alias.fullname,
                t.alias.module,
                t.alias.line,
                t.alias.column,
                alias_tvars=self.translate_variables(t.alias.alias_tvars),
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


class LiftAnyPlugin(Plugin):
    """Replace any occurrence of ``Any`` with ``object``."""

    def get_type_analyze_hook(
        self, fullname: str
    ) -> Callable[[AnalyzeTypeContext], Type] | None:
        if fullname == "typing.Any":

            def hook(ctx: AnalyzeTypeContext) -> Type:
                t = ctx.type
                return ctx.api.named_type(
                    "builtins.object", line=t.line, column=t.column
                )

            return hook
        elif fullname == "typing.Callable":

            def hook(ctx: AnalyzeTypeContext) -> Type:
                t = ctx.type
                api = ctx.api
                fallback = api.named_type("builtins.function")
                # Treat special cases before they hit
                # `api.analyze_callable_type(t)`
                if len(t.args) == 0:
                    object_type = api.named_type(
                        "builtins.object", line=t.line, column=t.column
                    )
                    return CallableType(
                        [object_type, object_type],
                        [ARG_STAR, ARG_STAR2],
                        [None, None],
                        ret_type=object_type,
                        fallback=fallback,
                        is_ellipsis_args=False,
                    ).accept(api)
                if len(t.args) == 2:
                    callable_args = t.args[0]
                    ret_type = t.args[1]
                    if isinstance(callable_args, EllipsisType):
                        object_type = api.named_type("builtins.object")
                        return CallableType(
                            [object_type, object_type],
                            [ARG_STAR, ARG_STAR2],
                            [None, None],
                            ret_type=ret_type,
                            fallback=fallback,
                            is_ellipsis_args=False,
                        ).accept(api)
                # Fallback the rest of cases to Mypy internal logic
                return api.analyze_callable_type(t)

            return hook
        return None

    def get_function_signature_hook(
        self, fullname: str
    ) -> Callable[[FunctionSigContext], FunctionLike] | None:
        if fullname in FUNCTIONS_ACCEPTING_COMPARISON_PROTOCOLS:

            def hook(ctx: FunctionSigContext) -> FunctionLike:
                args = ctx.args
                sig = ctx.default_signature
                if len(args) == 0 and len(args[0]) == 0:
                    return sig
                tt = get_proper_type(ctx.api.get_expression_type(args[0][0]))
                if isinstance(tt, Instance) and is_subtype(
                    tt.type, "typing.Iterable"
                ):
                    tt = tt.args[0]
                return sig.accept(FixSupportsComparison(tt))

            return hook

    def get_function_hook(
        self, fullname: str
    ) -> Callable[[FunctionContext], Type] | None:
        if fullname == "vutils.nox.utils.fix_decorator_type":

            def hook(ctx: FunctionContext) -> Type:
                emsg_deco = f"{fullname} must be used on a decorator"
                nmsg_redu = f"{fullname} is redundant at this place"
                api = ctx.api
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
                tvid = new_typevar_id(typ.variables, fullname)
                p_bare = new_paramspec(api, "P", tvid)
                p_args = p_bare.with_flavor(ParamSpecFlavor.ARGS)
                p_args.upper_bound = api.named_generic_type(
                    "builtins.tuple", [api.named_type("builtins.object")]
                )
                p_kwargs = p_bare.with_flavor(ParamSpecFlavor.KWARGS)
                p_kwargs.upper_bound = api.named_generic_type(
                    "builtins.dict",
                    [
                        api.named_type("builtins.str"),
                        api.named_type("builtins.object"),
                    ],
                )
                variables = (p_bare,) + typ.variables
                return typ.copy_modified(
                    arg_types=[
                        arg_typ.copy_modified(arg_types=[p_args, p_kwargs]),
                    ],
                    variables=variables,
                )

            return hook
        return None


def plugin(version: str) -> type[Plugin]:
    return LiftAnyPlugin
