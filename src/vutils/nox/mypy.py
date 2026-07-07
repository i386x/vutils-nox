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

#: Names of some important types
OBJECT_TYPE = "builtins.object"

#: Lists of cases that need to be handled specially by the plugin
COMPARISON_PROTOCOLS = (
    "_typeshed.SupportsDunderLT",
    "_typeshed.SupportsDunderGT",
)
FUNCTIONS_ACCEPTING_COMPARISON_PROTOCOLS = ("builtins.max", "builtins.min")

#: Modes of operation of :class:`.FixSupportsComparison` translator
NORMAL = 0
REPLACE = 1


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

    Translate :class:`object` in ``_typeshed.SupportsDunderLT`` and
    ``_typeshed.SupportsDunderGT`` argument to the given type.
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
        """
        prefix = t.prefix.accept(self)
        if not isinstance(prefix, Parameters):
            raise TypeError("`prefix` must be of `Parameters` type")
        return ParamSpecType(
            t.name,
            t.fullname,
            t.id,
            t.flavor,
            t.upper_bound.accept(self),
            default=t.default.accept(self),
            line=t.line,
            column=t.column,
            prefix=prefix,
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
        """
        if not isinstance(variables, (list, tuple)):
            raise TypeError("`variables` should be list or tuple")
        return type(variables)(v.accept(self) for v in variables)

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


def make_object(ctx: AnalyzeTypeContext) -> Type:
    """
    Make an :class:`object` type based on the context.

    :param ctx: The type analyzer context
    :return: the :class:`object` type
    """
    t = ctx.type
    return ctx.api.named_type(OBJECT_TYPE, line=t.line, column=t.column)


def handle_unspecified_parameters_in_callable(ctx: AnalyzeTypeContext) -> Type:
    """
    Handle bare :class:`typing.Callable` and ``Callable[..., T]``.

    :param ctx: The type analyzer context
    :return: the sanitized :class:`typing.Callable`

    These forms of :class:`typing.Callable`s contain :class:`typing.Any` so
    they are converted to ``Callable[[*object, **object], T]`` before ``mypy``
    takes care of them. Unfortunately, this may cause new kinds of problems,
    like type incompatibility caused by changed variance. Such cases must be
    handled further in followup hooks.
    """
    t = ctx.type
    api = ctx.api
    fallback = api.named_type("builtins.function")

    # Treat special cases before they hit `api.analyze_callable_type(t)`
    if len(t.args) == 0:
        object_type = api.named_type(OBJECT_TYPE, line=t.line, column=t.column)
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
    # Fallback the rest of cases to `mypy` internal logic
    return api.analyze_callable_type(t)


class LiftAnyPlugin(Plugin):
    """Replace any occurrence of :class:`typing.Any` with :class:`object`."""

    __slots__ = ()

    def get_type_analyze_hook(
        self, fullname: str
    ) -> Callable[[AnalyzeTypeContext], Type] | None:
        if fullname == "typing.Any":
            return make_object
        if fullname == "typing.Callable":
            return handle_unspecified_parameters_in_callable
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
                if isinstance(tt, Instance) and is_subtype_of(
                    tt.type, "typing.Iterable"
                ):
                    tt = tt.args[0]
                return sig.accept(FixSupportsComparison(tt))

            return hook
        return None

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


def plugin(unused_version: str) -> type[Plugin]:
    """Return plugin."""
    return LiftAnyPlugin
