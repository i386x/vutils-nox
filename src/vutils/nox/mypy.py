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
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
    Sequence,
)
from typing import (
    Generator,
    Literal,
    Protocol,
    TypeDict,
    TypeVar,
    Unpack,
    overload,
)

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
    DeletedType,
    EllipsisType,
    ErasedType,
    FunctionLike,
    Instance,
    LiteralType,
    NoneType,
    Overloaded,
    Parameters,
    ParamSpecFlavor,
    ParamSpecType,
    PartialType,
    TupleType,
    Type,
    TypeAliasType,
    TypeOfAny,
    TypeType,
    TypeVarId,
    TypeVarLikeType,
    TypeVarTupleType,
    TypeVarType,
    TypedDictType,
    UnboundType,
    UninhabitatedType,
    UnionType,
    UnpackType,
    get_proper_type,
)

#: Parameters, keys, and properties
KW_ACTION: Literal["action"] = "action"
KW_ALIAS: Literal["alias"] = "alias"
KW_ARG_TYPES: Literal["arg_types"] = "arg_types"
KW_ARGS: Literal["args"] = "args"
KW_DEFAULT: Literal["default"] = "default"
KW_DETAIL: Literal["detail"] = "detail"
KW_FALLBACK: Literal["fallback"] = "fallback"
KW_ITEM: Literal["item"] = "item"
KW_ITEMS: Literal["items"] = "items"
KW_KV_ITEMS: Literal["kv_items"] = "kv_items"
KW_LAST_KNOWN_VALUE: Literal["last_known_value"] = "last_known_value"
KW_PREFIX: Literal["prefix"] = "prefix"
KW_RET_TYPE: Literal["ret_type"] = "ret_type"
KW_TYP: Literal["typ"] = "typ"
KW_UPPER_BOUND: Literal["upper_bound"] = "upper_bound"
KW_VALUES: Literal["values"] = "values"
KW_VARIABLES: Literal["variables"] = "variables"

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


class TypeRuleAction(Protocol):
    @overload
    def __call__(t: UnboundType, args: Sequence[Type]) -> Type: ...
    @overload
    def __call__(
        t: Instance, args: Sequence[Type], last_known_value: LiteralType
    ) -> Type: ...
    @overload
    def __call__(
        t: TypeVarType,
        values: Sequence[Type],
        upper_bound: Type,
        default: Type,
    ) -> Type: ...
    @overload
    def __call__(
        t: ParamSpecType, upper_bound: Type, default: Type, prefix: Parameters
    ) -> Type: ...
    @overload
    def __call__(
        t: Parameters,
        arg_types: Sequence[Type],
        variables: Sequence[TypeVarLikeType],
    ) -> Type: ...
    @overload
    def __call__(
        t: TypeVarTupleType, upper_bound: Type, default: Type
    ) -> Type: ...
    @overload
    def __call__(t: UnpackType, typ: Type) -> Type: ...
    @overload
    def __call__(
        t: CallableType,
        arg_types: Sequence[Type],
        ret_type: Type,
        variables: Sequence[TypeVarLikeType],
    ) -> Type: ...
    @overload
    def __call__(
        t: TupleType, items: Sequence[Type], fallback: Instance
    ) -> Type: ...
    @overload
    def __call__(
        t: TypedDictType, items: Mapping[str, Type], fallback: Instance
    ) -> Type: ...
    @overload
    def __call__(t: LiteralType, fallback: Instance) -> Type: ...
    @overload
    def __call__(t: UnionType, items: Sequence[Type]) -> Type: ...
    @overload
    def __call__(t: Overloaded, items: Sequence[CallableType]) -> Type: ...
    @overload
    def __call__(t: TypeType, item: Type) -> Type: ...
    def __call__(t: Type) -> Type: ...


class TypeRuleArgs(TypedDict, total=False):
    """:class:`.TypeRule` key-value arguments definition."""

    #: The additional detail about type, e.g. full name
    detail: str
    #: The pair of type rules matching the target and type variables of the
    #: alias
    alias: tuple[TypeRule, Sequence[TypeRule]]
    #: The sequence of type rules matching type arguments
    args: Sequence[TypeRule]
    #: The sequence of type rules matching argument types
    arg_types: Sequence[TypeRule]
    #: The sequence of type rules matching type items
    items: Sequence[TypeRule]
    #: The mapping between the name of a typed dictionary item and a type rule
    #: matching the typed dictionary item of the same name
    kv_items: Mapping[str, TypeRule]
    #: The sequence of type rules matching type variables values
    values: Sequence[TypeRule]
    #: The sequence of type rules matching type variables
    variables: Sequence[TypeRule]
    #: The type rule matching the ``type`` attribute of
    #: :class:`mypy.types.UnpackType`
    typ: TypeRule
    #: The type rule matching the type item
    item: TypeRule
    #: The type rule matching the return type
    ret_type: TypeRule
    #: The type rule matching the type variable's upper bound type
    upper_bound: TypeRule
    #: The type rule matching the type variable's default type
    default: TypeRule
    #: The type rule matching the fallback type
    fallback: TypeRule
    #: The type rule matching the parameters specification's prefix type
    prefix: TypeRule
    #: The type rule matching the ``last_known_value`` attribute of
    #: :class:`mypy.types.Instance`
    last_known_value: TypeRule
    #: The action to be invoked to transform the type. If not specified, the
    #: type will be passed as it is or copied with its parts transformed,
    #: depending on the type
    action: TypeRuleAction


class TypeRule:
    """A rule describing a type."""

    #: The type the rule should match
    ttype: type[Type]
    #: Additional key-value arguments carrying details about the matching type
    kwargs: TypeRuleArgs

    __slots__ = ("ttype", "kwargs")

    def __init__(
        self, ttype: type[Type], **kwargs: Unpack[TypeRuleArgs]
    ) -> None:
        """
        Initialize the type rule.

        :param ttype: The expected matching type
        :param kwargs: Additional details about the expected matching type

        Supported key-value arguments are:

        :into_list:`.TypeRuleArgs`
        """
        self.ttype = ttype
        self.kwargs = kwargs

    @property
    def action(self) -> TypeRuleAction | None:
        """
        Get the action associated with the rule.

        :return: the action associated with the rule or :obj:`None` if there is
            no such action
        """
        if KW_ACTION not in self.kwargs:
            return None
        return self.kwargs[KW_ACTION]

    def check(self, t: Type) -> None:
        """
        Check whether :xarg:`t` matches the rule.

        :param t: The type
        :raises .TypeMatchError: when :xarg:`t` does not match the rule
        :raises TypeError: when the rule is missing additional required
            information
        """
        if self.ttype is not type(t):
            raise TypeMatchError(f"Expected an instance of {type(t)!r}")
        if isinstance(t, Instance):
            if KW_DETAIL not in self.kwargs:
                raise TypeError(f"Missing `{KW_DETAIL}`")
            detail = self.kwargs[KW_DETAIL]
            if t.type.fullname != detail:
                raise TypeMatchError(f"Expected `Instance({detail})`")

    @staticmethod
    def traverse_type(
        rule: TypeRule, t: Type, transformer: TypeTransformer
    ) -> Type:
        """
        Traverse a type.

        :param rule: The type matching rule
        :param t: The type
        :param transformer: The type transformer
        :return: the transformed traversed type
        """
        with transformer.with_rule(rule):
            return t.accept(transformer)

    @staticmethod
    def traverse_type_sequence(
        rules: Sequence[TypeRule],
        sequence: Sequence[Type],
        transformer: TypeTransformer,
    ) -> Sequence[Type]:
        """
        Traverse a sequence of types.

        :param rules: The sequence of type matching rules
        :param sequence: The sequence of types
        :param transformer: The type transformer
        :return: the list of transformed traversed types
        :raises .TypeMatchError: when the sequence of types does not match the
            sequence of rules

        A type should match a rule on the same position in the sequence.
        """
        if len(rules) != len(sequence):
            raise TypeMatchError(
                "Sequence length does not match with the number of rules"
            )
        return [
            self.traverse_type(rule, item, transformer)
            for (rule, item) in zip(rules, sequence)
        ]

    def traverse_alias(
        self, alias: TypeAlias | None, transformer: TypeTransformer
    ) -> TypeAlias | None:
        """
        Traverse the type alias.

        :param args: The type alias
        :param transformer: The type transformer
        """
        if KW_ALIAS not in self.kwargs:
            if alias is None:
                return None
            raise TypeError(f"Missing `{KW_ALIAS}`")
        if alias is None:
            raise TypeMatchError("Type alias is `None`")
        alias_target_rule, alias_tvars_rules = self.kwargs[KW_ALIAS]
        alias_target = self.traverse_type(
            alias_target_rule, alias.target, transformer
        )
        alias_tvars = [
            verify_type(
                self.traverse_type(rule, tv, transformer),
                TypeVarLikeType,
            )
            for (rule, tv) in zip(alias_tvars_rules, alias.alias_tvars)
        ]

    def traverse_args(
        self, args: Sequence[Type], transformer: TypeTransformer
    ) -> Sequence[Type]:
        """
        Traverse type arguments.

        :param args: The sequence of type arguments
        :param transformer: The type transformer
        :return: the list of transformed traversed type arguments
        :raises TypeError: when the rule is missing sub-rules for :xarg:`args`
        """
        if KW_ARGS not in self.kwargs:
            raise TypeError(f"Missing `{KW_ARGS}`")
        return self.traverse_type_sequence(
            self.kwargs[KW_ARGS], args, transformer
        )

    def traverse_arg_types(
        self, arg_types: Sequence[Type], transformer: TypeTransformer
    ) -> Sequence[Type]:
        """
        Traverse argument types.

        :param arg_types: The sequence of argument types
        :param transformer: The type transformer
        :return: the list of transformed traversed argument types
        :raises TypeError: when the rule is missing sub-rules for
            :xarg:`arg_types`
        """
        if KW_ARG_TYPES not in self.kwargs:
            raise TypeError(f"Missing `{KW_ARG_TYPES}`")
        return self.traverse_type_sequence(
            self.kwargs[KW_ARG_TYPES], arg_types, transformer
        )

    def traverse_items(
        self, items: Sequence[Type], transformer: TypeTransformer
    ) -> Sequence[Type]:
        """
        Traverse type items.

        :param items: The sequence of type items
        :param transformer: The type transformer
        :return: the list of transformed traversed type items
        :raises TypeError: when the rule is missing sub-rules for :xarg:`items`
        """
        if KW_ITEMS not in self.kwargs:
            raise TypeError(f"Missing `{KW_ITEMS}`")
        return self.traverse_type_sequence(
            self.kwargs[KW_ITEMS], items, transformer
        )

    def traverse_citems(
        self, items: Sequence[CallableType], transformer: TypeTransformer
    ) -> Sequence[CallableType]:
        """
        Traverse callable type items.

        :param items: The sequence of callable type items
        :param transformer: The type transformer
        :return: the list of transformed traversed callable type items
        :raises TypeError: when the rule is missing sub-rules for :xarg:`items`
        :raises .TypeMatchError: when the sequence of rules does not match the
            sequence of types
        """
        if KW_ITEMS not in self.kwargs:
            raise TypeError(f"Missing `{KW_ITEMS}`")
        rules = self.kwargs[KW_ITEMS]
        if len(rules) != len(items):
            raise TypeMatchError("Items and rules do not match in count")
        return [
            verify_type(
                self.traverse_type(rule, item, transformer), CallableType
            )
            for (rule, item) in zip(rules, items)
        ]

    def traverse_kv_items(
        self, items: Mapping[str, Type], transformer: TypeTransformer
    ) -> Mapping[str, Type]:
        """
        Traverse item name to item type mapping.

        :param items: The item name to item type mapping
        :param transformer: The type transformer
        :return: the corresponding dictionary with transformed traversed item
            types
        :raise TypeError: when the rule is missing a corresponding mapping of
            sub-rules for :xarg:`items`
        :raise TypeMatchError: when the two mappings do not match
        """
        if KW_KV_ITEMS not in self.kwargs:
            raise TypeError(f"Missing `{KW_KV_ITEMS}`")
        rules = self.kwargs[KW_KV_ITEMS]
        if len(rules) != len(items):
            raise TypeMatchError(f"Items and rules do not match in count")
        result: MutableMapping[str, Type] = {}
        for (name, typ) in items.items():
            if name not in rules:
                raise TypeMatchError(f"No type matching rule for `{name}`")
            result[name] = self.traverse_type(rules[name], typ, transformer)
        return result

    def traverse_values(
        self, values: Sequence[Type], transformer: TypeTransformer
    ) -> Sequence[Type]:
        """
        Traverse type variable values.

        :param values: The sequence of type variable values
        :param transformer: The type transformer
        :return: the list of transformed traversed type variable values
        :raises TypeError: when the rule is missing sub-rules for
            :xarg:`values`
        """
        if KW_VALUES not in self.kwargs:
            raise TypeError(f"Missing `{KW_VALUES}`")
        return self.traverse_type_sequence(
            self.kwargs[KW_VALUES], values, transformer
        )

    def traverse_variables(
        self,
        variables: Sequence[TypeVarLikeType],
        transformer: TypeTransformer,
    ) -> Sequence[TypeVarLikeType]:
        """
        Traverse type variables.

        :param variables: The sequence of type variables
        :param transformer: The type transformer
        :return: the list of transformed traversed type variables
        :raises TypeError: when the rule is missing sub-rules for
            :xarg:`variables`
        """
        if KW_VARIABLES not in self.kwargs:
            raise TypeError(f"Missing `{KW_VARIABLES}`")
        return verify_type(
            self.traverse_type_sequence(
                self.kwargs[KW_VARIABLES], variables, transformer
            ),
            TypeVarLikeType,
        )

    def traverse_typ(self, t: Type, transformer: TypeTransformer) -> Type:
        """
        Traverse the underlying type.

        :param t: The underlying type
        :param transformer: The type transformer
        :return: the transformed traversed underlying type
        :raises TypeError: when the rule is missing a sub-rule for :xarg:`t`
        """
        if KW_TYP not in self.kwargs:
            raise TypeError(f"Missing `{KW_TYP}`")
        return self.traverse_type(self.kwargs[KW_TYP], t, transformer)

    def traverse_item(self, t: Type, transformer: TypeTransformer) -> Type:
        """
        Traverse the type item.

        :param t: The type item
        :param transformer: The type transformer
        :return: the transformed traversed type item
        :raises TypeError: when the rule is missing a sub-rule for :xarg:`t`
        """
        if KW_ITEM not in self.kwargs:
            raise TypeError(f"Missing `{KW_ITEM}`")
        return self.traverse_type(self.kwargs[KW_ITEM], t, transformer)

    def traverse_ret_type(self, t: Type, transformer: TypeTransformer) -> Type:
        """
        Traverse the return type.

        :param t: The return type
        :param transformer: The type transformer
        :return: the transformed traversed return type
        :raises TypeError: when the rule is missing a sub-rule for :xarg:`t`
        """
        if KW_RET_TYPE not in self.kwargs:
            raise TypeError(f"Missing `{KW_RET_TYPE}`")
        return self.traverse_type(self.kwargs[KW_RET_TYPE], t, transformer)

    def traverse_upper_bound(
        self, t: Type, transformer: TypeTransformer
    ) -> Type:
        """
        Traverse the type variable's upper bound type.

        :param t: The type variable's upper bound type
        :param transformer: The type transformer
        :return: the transformed traversed type variable's upper bound type
        :raises TypeError: when the rule is missing a sub-rule for :xarg:`t`
        """
        if KW_UPPER_BOUND not in self.kwargs:
            raise TypeError(f"Missing `{KW_UPPER_BOUND}`")
        return self.traverse_type(self.kwargs[KW_UPPER_BOUND], t, transformer)

    def traverse_default(self, t: Type, transformer: TypeTransformer) -> Type:
        """
        Traverse the type variable's default type.

        :param t: The type variable's default type
        :param transformer: The type transformer
        :return: the transformed traversed type variable's default type
        :raises TypeError: when the rule is missing a sub-rule for :xarg:`t`
        """
        if KW_DEFAULT not in self.kwargs:
            raise TypeError(f"Missing `{KW_DEFAULT}`")
        return self.traverse_type(self.kwargs[KW_DEFAULT], t, transformer)

    def traverse_fallback(
        self, t: Type, transformer: TypeTransformer
    ) -> Instance:
        """
        Traverse the fallback type.

        :param t: The fallback type
        :param transformer: The type transformer
        :return: the transformed traversed fallback type
        :raises TypeError: when the rule is missing a sub-rule for :xarg:`t`
        """
        if KW_FALLBACK not in self.kwargs:
            raise TypeError(f"Missing `{KW_FALLBACK}`")
        return verify_type(
            self.traverse_type(self.kwargs[KW_FALLBACK], t, transformer),
            Instance,
        )

    def traverse_prefix(
        self, t: Type, transformer: TypeTransformer
    ) -> Parameters:
        """
        Traverse the parameters specification's prefix type.

        :param t: The parameters specification's prefix type
        :param transformer: The type transformer
        :return: the transformed traversed parameters specification's prefix
            type
        :raises TypeError: when the rule is missing a sub-rule for :xarg:`t`
        """
        if KW_PREFIX not in self.kwargs:
            raise TypeError(f"Missing `{KW_PREFIX}`")
        return verify_type(
            self.traverse_type(self.kwargs[KW_PREFIX], t, transformer),
            Parameters,
        )

    def traverse_last_known_value(
        self, t: Type, transformer: TypeTransformer
    ) -> LiteralType:
        """
        Traverse *last known value*.

        :param t: The *last known value* type
        :param transformer: The type transformer
        :return: the transformed traversed *last known value* type
        :raises TypeError: when the rule is missing a sub-rule for :xarg:`t`
        """
        if KW_LAST_KNOWN_VALUE not in self.kwargs:
            raise TypeError(f"Missing `{KW_LAST_KNOWN_VALUE}`")
        return verify_type(
            self.traverse_type(
                self.kwargs[KW_LAST_KNOWN_VALUE], t, transformer
            ),
            LiteralType,
        )


class TypeTransformer(TypeTranslator):
    """
    Type transformer.

    Like :class:`mypy.type_visitor.TypeTranslator` but also checks if the type
    matches the rule.
    """

    #: The type matching rule
    rule: TypeRule

    __slots__ = ("rule",)

    def __init__(self, rule: TypeRule) -> None:
        """
        Initialize the transformer.

        :param rule: The type matching rule
        """
        super().__init__()
        self.rule = rule

    @contextlib.contextmanager
    def with_rule(self, rule: TypeRule) -> Generator[None, None, None]:
        """
        Create a new context where the new rule applies.

        :param rule: The new type matching rule
        :return: the generator managing the context
        """
        old_rule = self.rule
        try:
            self.rule = rule
            yield
        finally:
            self.rule = old_rule

    def transform_simple_type(self, t: Type, /) -> Type:
        """
        Transform simple type.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        action = self.rule.action
        if action:
            return action(t)
        return t

    def visit_unbound_type(self, t: UnboundType, /) -> Type:
        """
        Transform :class:`mypy.types.UnboundType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        args = self.rule.traverse_args(t.args, self)
        action = self.rule.action
        if action:
            return action(t, args)
        return t.copy_modified(args=args)

    def visit_any(self, t: AnyType, /) -> Type:
        """
        Transform :class:`mypy.types.AnyType`.

        :param t: The type
        :return: the transformed type
        """
        return self.transform_simple_type(t)

    def visit_none_type(self, t: NoneType, /) -> Type:
        """
        Transform :class:`mypy.types.NoneType`.

        :param t: The type
        :return: the transformed type
        """
        return self.transform_simple_type(t)

    def visit_uninhabited_type(self, t: UninhabitedType, /) -> Type:
        """
        Transform :class:`mypy.types.UninhabitedType`.

        :param t: The type
        :return: the transformed type
        """
        return self.transform_simple_type(t)

    def visit_erased_type(self, t: ErasedType, /) -> Type:
        """
        Transform :class:`mypy.types.ErasedType`.

        :param t: The type
        :return: the transformed type
        """
        return self.transform_simple_type(t)

    def visit_deleted_type(self, t: DeletedType, /) -> Type:
        """
        Transform :class:`mypy.types.DeletedType`.

        :param t: The type
        :return: the transformed type
        """
        return self.transform_simple_type(t)

    def visit_instance(self, t: Instance, /) -> Type:
        """
        Transform :class:`mypy.types.Instance`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        args = self.rule.traverse_args(t.args, self)
        last_known_value: LiteralType | None = None
        if t.last_known_value is not None:
            last_known_value = self.rule.traverse_last_known_value(
                t.last_known_value, self
            )
        action = self.rule.action
        if action:
            return action(t, args, last_known_value)
        return Instance(
            typ=t.type,
            args=args,
            line=t.line,
            column=t.column,
            last_known_value=last_known_value,
            extra_attrs=t.extra_attrs,
        )

    def visit_type_var(self, t: TypeVarType, /) -> Type:
        """
        Transform :class:`mypy.types.TypeVarType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        values = self.rule.traverse_values(t.values, self)
        upper_bound = self.rule.traverse_upper_bound(t.upper_bound, self)
        default = self.rule.traverse_default(t.default, self)
        action = self.rule.action
        if action:
            return action(t, values, upper_bound, default)
        return t.copy_modified(
            values=values, upper_bound=upper_bound, default=default
        )

    def visit_param_spec(self, t: ParamSpecType, /) -> Type:
        """
        Transform :class:`mypy.types.ParamSpecType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        upper_bound = self.rule.traverse_upper_bound(t.upper_bound, self)
        default = self.rule.traverse_default(t.default, self)
        prefix = self.rule.traverse_prefix(t.prefix, self)
        action = self.rule.action
        if action:
            return action(t, upper_bound, default, prefix)
        return ParamSpecType(
            t.name,
            t.fullname,
            t.id,
            t.flavor,
            upper_bound,
            default=default,
            line=t.line,
            column=t.column,
            prefix=prefix,
        )

    def visit_parameters(self, t: Parameters, /) -> Type:
        """
        Transform :class:`mypy.types.Parameters`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        arg_types = self.rule.traverse_arg_types(t.arg_types, self)
        variables = self.rule.traverse_variables(t.variables, self)
        action = self.rule.action
        if action:
            return action(t, arg_types, variables)
        return t.copy_modified(arg_types=arg_types, variables=variables)

    def visit_type_var_tuple(self, t: TypeVarTupleType, /) -> Type:
        """
        Transform :class:`mypy.types.TypeVarTupleType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        upper_bound = self.rule.traverse_upper_bound(t.upper_bound, self)
        default = self.rule.traverse_default(t.default, self)
        action = self.rule.action
        if action:
            return action(t, upper_bound, default)
        return t.copy_modified(upper_bound=upper_bound, default=default)

    def visit_partial_type(self, t: PartialType, /) -> Type:
        """
        Transform :class:`mypy.types.PartialType`.

        :param t: The type
        :return: the transformed type
        """
        return self.transform_simple_type(t)

    def visit_unpack_type(self, t: UnpackType, /) -> Type:
        """
        Transform :class:`mypy.types.UnpackType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        typ = self.rule.traverse_typ(t.type, self)
        action = self.rule.action
        if action:
            return action(t, typ)
        return UnpackType(
            typ,
            line=t.line,
            column=t.column,
            from_star_syntax=t.from_star_syntax,
        )

    def visit_callable_type(self, t: CallableType, /) -> Type:
        """
        Transform :class:`mypy.types.CallableType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        arg_types = self.rule.traverse_arg_types(t.arg_types, self)
        ret_type = self.rule.traverse_ret_type(t.ret_type, self)
        variables = self.rule.traverse_variables(t.variables, self)
        action = self.rule.action
        if action:
            return action(t, arg_types, ret_type, variables)
        return t.copy_modified(
            arg_types=arg_types, ret_type=ret_type, variables=variables
        )

    def visit_tuple_type(self, t: TupleType, /) -> Type:
        """
        Transform :class:`mypy.types.TupleType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        items = self.rule.traverse_items(t.items, self)
        fallback = self.rule.traverse_fallback(t.partial_fallback, self)
        action = self.rule.action
        if action:
            return action(t, items, fallback)
        return TupleType(
            items, fallback, line=t.line, column=t.column, implicit=t.implicit
        )

    def visit_typeddict_type(self, t: TypedDictType, /) -> Type:
        """
        Transform :class:`TypedDictType`.

        :param t: The type
        :return: the transformed type
        """
        cached = self.get_cached(t)
        if cached:
            return cached
        self.rule.check(t)
        items = self.rule.traverse_kv_items(t.items, self)
        fallback = self.rule.traverse_fallback(t.fallback, self)
        action = self.rule.action
        result = (
            action(t, items, fallback) if action
            else TypedDictType(
                items,
                t.required_keys,
                t.readonly_keys,
                fallback,
                line=t.line,
                column=t.column,
            )
        )
        self.set_cached(t, result)
        return result

    def visit_literal_type(self, t: LiteralType, /) -> Type:
        """
        Transform :class:`mypy.types.LiteralType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        fallback = self.rule.traverse_fallback(t.fallback, self)
        action = self.rule.action
        if action:
            return action(t, fallback)
        return LiteralType(value, fallback, line=t.line, column=t.column)

    def visit_union_type(self, t: UnionType, /) -> Type:
        """
        Transform :class:`mypy.types.UnionType`.

        :param t: The type
        :return: the transformed type
        """
        use_cache = len(t.items) > 3
        cached = self.get_cached(t)
        if use_cache and cached:
            return cached
        self.rule.check(t)
        items = self.rule.traverse_items(t.items, self)
        action = self.rule.action
        result = (
            action(t, items) if action
            else UnionType(
                items,
                line=t.line,
                column=t.column,
                is_evaluated=t.is_evaluated,
                uses_pep604_syntax=t.uses_pep604_syntax,
            )
        )
        if use_cache:
            self.set_cached(t, result)
        return result

    def visit_overloaded(self, t: Overloaded, /) -> Type:
        """
        Transform :class:`mypy.types.Overloaded`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        items = self.rule.traverse_citems(t.items, self)
        action = self.rule.action
        if action:
            return action(t, items)
        return Overloaded(items)

    def visit_type_type(self, t: TypeType, /) -> Type:
        """
        Transform :class:`mypy.types.TypeType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        item = self.rule.traverse_item(t.item, self)
        action = self.rule.action
        if action:
            return action(t, item)
        return TypeType.make_normalized(
            item, line=t.line, column=t.column, is_type_form=t.is_type_form
        )

    def visit_type_alias_type(self, t: TypeAliasType, /) -> Type:
        """
        Transform :class:`mypy.types.TypeAliasType`.

        :param t: The type
        :return: the transformed type
        """
        self.rule.check(t)
        alias: TypeAlias | None = None
        if t.alias:

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
