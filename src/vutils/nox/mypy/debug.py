#
# File:    ./src/vutils/nox/mypy/debug.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-07-31 07:46:02 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Type debugging utilities."""

import random
from collections.abc import MutableMapping, MutableSequence

from mypy.nodes import (
    Decorator,
    FuncDef,
    NameExpr,
    Node,
    TypeAlias,
    TypeParam,
    Var,
)
from mypy.types import (
    AnyType,
    CallableType,
    Instance,
    NoneType,
    ParamSpecType,
    TupleType,
    Type,
    TypeAliasType,
    TypeVarId,
    TypeVarType,
    UnionType,
)

#: The handy string constants used during printing
INDENTATION_BLOCK = "  "
LBRACE = "{"
RBRACE = "}"

#: The alternative names for objects used instead of their ids
MEMORABLE_NAMES = (
    "affordable",
    "animal",
    "apple",
    "bookshelf",
    "bread",
    "business",
    "calendar",
    "circle",
    "coal",
    "delivery",
    "downstairs",
    "drink",
    "elephant",
    "empathy",
    "equity",
    "firefly",
    "flowers",
    "football",
    "gate",
    "gathering",
    "goat",
    "highlands",
    "holidays",
    "humming",
    "ignored",
    "information",
    "implicit",
    "jalapeno",
    "joker",
    "justify",
    "keyboard",
    "kitten",
    "knowledge",
    "landlord",
    "loaded",
    "lunar",
    "mechanical",
    "milk",
    "month",
    "nature",
    "needle",
    "nonsense",
    "ogre",
    "olive",
    "oxygen",
    "pencil",
    "potato",
    "punctuation",
    "quadratic",
    "quarter",
    "queen",
    "rapid",
    "render",
    "rock",
    "saturation",
    "software",
    "surface",
    "teapot",
    "token",
    "tree",
    "ugly",
    "ultraviolet",
    "unique",
    "variable",
    "virtual",
    "vote",
    "wave",
    "wicked",
    "wool",
    "xenon",
    "xerox",
    "xylophone",
    "year",
    "yellow",
    "young",
    "zero",
    "zinc",
    "zookeeper",
)


class Visited:
    """The registry for visited objects."""

    #: The pool of alternative names for visited objects
    __names: MutableSequence[str]
    #: The registry for visited objects
    __registry: MutableMapping[int, str]

    __slots__ = ("__names", "__registry")

    def __init__(self) -> None:
        """Initialize the registry."""
        self.__names = list(MEMORABLE_NAMES)
        random.shuffle(self.__names)
        self.__registry = {}

    def contains(self, obj: object) -> bool:
        """
        Test whether an object is in the registry.

        :param obj: The object
        :return: :obj:`True` if the object is in the registry
        """
        return id(obj) in self.__registry

    def get(self, obj: object) -> str:
        """
        Get the alternative name of a visited object.

        :param obj: The visited object
        :return: the alternative name associated with the visited object

        If the object is not in the registry, its :func:`id` is used as its
        alternative name.
        """
        key = id(obj)
        return self.__registry.get(key, f"{key}")

    def add(self, obj: object) -> None:
        """
        Add a visited object to the registry.

        :param obj: The visited object

        When registered, an alternative name is given to the visited object. If
        the pool of alternative names is exhausted, :func:`id` of the visited
        object is used.
        """
        key = id(obj)
        if key not in self.__registry:
            self.__registry[key] = (
                self.__names.pop() if self.__names else f"{key}"
            )


def print_typeparam(
    tp: TypeParam,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a type parameter.

    :param tp: The type parameter
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}TypeParam {LBRACE}")
    print(f"{pad}  __id__: #node({visited.get(tp)}),")
    print(f"{pad}  name: {tp.name},")
    print(f"{pad}  kind: {tp.kind},")
    if tp.upper_bound is None:
        print(f"{pad}  upper_bound: None,")
    else:
        print(f"{pad}  upper_bound:")
        print_type(tp.upper_bound, visited, indent + 2)
    print(f"{pad}  values: [")
    for tt in tp.values:
        print_type(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    if tp.default is None:
        print(f"{pad}  default: None,")
    else:
        print(f"{pad}  default:")
        print_type(tp.default, visited, indent + 2)
    print(f"{pad}{RBRACE}{trailer}")


def print_funcdef_node(
    node: FuncDef,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.nodes.FuncDef` node.

    :param node: The node
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}FuncDef {LBRACE}")
    print(f"{pad}  __id__: #node({visited.get(node)}),")
    print(f"{pad}  name: {node.name},")
    if node.type is None:
        print(f"{pad}  type: None,")
    else:
        print(f"{pad}  type:")
        print_type(node.type, visited, indent + 2)
    if node.type_args is None:
        print(f"{pad}  type_args: None,")
    else:
        print(f"{pad}  type_args: [")
        for tt in node.type_args:
            print_typeparam(tt, visited, indent + 2, ",")
        print(f"{pad}  ],")
    print(f"{pad}{RBRACE}{trailer}")


def print_decorator_node(
    node: Decorator,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.nodes.Decorator` node.

    :param node: The node
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}Decorator {LBRACE}")
    print(f"{pad}  __id__: #node({visited.get(node)}),")
    print(f"{pad}  func:")
    print_node(node.func, visited, indent + 2)
    print(f"{pad}  decorators: [")
    for tt in node.decorators:
        print_node(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    print(f"{pad}  var:")
    print_node(node.var, visited, indent + 2)
    print(f"{pad}{RBRACE}{trailer}")


def print_var_node(
    node: Var,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.nodes.Var` node.

    :param node: The node
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}Var {LBRACE}")
    print(f"{pad}  __id__: #node({visited.get(node)}),")
    print(f"{pad}  fullname: {node.fullname},")
    if node.type is None:
        print(f"{pad}  type: None,")
    else:
        print(f"{pad}  type:")
        print_type(node.type, visited, indent + 2)
    print(f"{pad}{RBRACE}{trailer}")


def print_name_expr_node(
    node: NameExpr,
    unused_visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.nodes.NameExpr` node.

    :param node: The node
    :param unused_visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f'{pad}NameExpr("{node.name}"){trailer}')


def print_typealias_node(
    node: TypeAlias,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.nodes.TypeAlias` node.

    :param node: The node
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}TypeAlias {LBRACE}")
    print(f"{pad}  __id__: #node({visited.get(node)}),")
    print(f"{pad}  fullname: {node.fullname},")
    print(f"{pad}  target:")
    print_type(node.target, visited, indent + 2)
    print(f"{pad}  alias_tvars: [")
    for tt in node.alias_tvars:
        print_type(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    print(f"{pad}{RBRACE}{trailer}")


def print_node(
    node: Node,
    visited: Visited | None = None,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a node.

    :param node: The node
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    :raises TypeError: when an unknown node is tried to be printed
    """
    if visited is None:
        visited = Visited()
    if visited.contains(node):
        pad = INDENTATION_BLOCK * indent
        print(
            f"{pad}{node.__class__.__name__} {LBRACE}"
            f"[[visited @ #node({visited.get(node)})]], ..."
            f"{RBRACE}{trailer}"
        )
        return
    visited.add(node)

    if isinstance(node, FuncDef):
        print_funcdef_node(node, visited, indent, trailer)
    elif isinstance(node, Decorator):
        print_decorator_node(node, visited, indent, trailer)
    elif isinstance(node, Var):
        print_var_node(node, visited, indent, trailer)
    elif isinstance(node, NameExpr):
        print_name_expr_node(node, visited, indent, trailer)
    elif isinstance(node, TypeAlias):
        print_typealias_node(node, visited, indent, trailer)
    else:
        raise TypeError(f"Unknown node: {node.__class__.__name__}")


def print_typealias_type(
    t: TypeAliasType,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.types.TypeAliasType` type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}TypeAliasType {LBRACE}")
    print(f"{pad}  __id__: #{visited.get(t)},")
    if t.alias is None:
        print(f"{pad}  alias: None,")
    else:
        print(f"{pad}  alias:")
        print_node(t.alias, visited, indent + 2)
    print(f"{pad}  args: [")
    for tt in t.args:
        print_type(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    print(f"{pad}  type_ref: {t.type_ref},")
    print(f"{pad}  line: {t.line},")
    print(f"{pad}  column: {t.column},")
    print(f"{pad}{RBRACE}{trailer}")


def show_typevarid(tvid: TypeVarId) -> str:
    """
    Show :class:`mypy.types.TypeVarId` internals.

    :param tvid: The type variable id
    :return: the type variable id internals as string
    """
    return (
        "TypeVarId("
        f"raw_id: {tvid.raw_id}"
        f", meta_level: {tvid.meta_level}"
        f", namespace: {tvid.namespace}"
        ")"
    )


def print_typevar_type(
    t: TypeVarType,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.types.TypeVarType` type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}TypeVarType {LBRACE}")
    print(f"{pad}  __id__: #{visited.get(t)},")
    print(f"{pad}  name: {t.name},")
    print(f"{pad}  fullname: {t.fullname},")
    print(f"{pad}  id: {show_typevarid(t.id)},")
    print(f"{pad}  values: [")
    for tt in t.values:
        print_type(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    print(f"{pad}  upper_bound:")
    print_type(t.upper_bound, visited, indent + 2)
    print(f"{pad}  default:")
    print_type(t.default, visited, indent + 2)
    print(f"{pad}  variance: {t.variance},")
    print(f"{pad}  line: {t.line},")
    print(f"{pad}  column: {t.column},")
    print(f"{pad}{RBRACE}{trailer}")


def print_paramspec_type(
    t: ParamSpecType,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.types.ParamSpecType` type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}ParamSpecType {LBRACE}")
    print(f"{pad}  __id__: #{visited.get(t)},")
    print(f"{pad}  name: {t.name},")
    print(f"{pad}  fullname: {t.fullname},")
    print(f"{pad}  id: {show_typevarid(t.id)},")
    print(f"{pad}  flavor: {t.flavor},")
    print(f"{pad}  upper_bound:")
    print_type(t.upper_bound, visited, indent + 2)
    print(f"{pad}  default:")
    print_type(t.default, visited, indent + 2)
    print(f"{pad}  line: {t.line},")
    print(f"{pad}  column: {t.column},")
    print(f"{pad}  prefix: {t.prefix},")
    print(f"{pad}{RBRACE}{trailer}")


def print_any_type(
    t: AnyType,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.types.AnyType` type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}AnyType {LBRACE}")
    print(f"{pad}  __id__: #{visited.get(t)},")
    print(f"{pad}  type_of_any: {t.type_of_any},")
    if t.source_any is None:
        print(f"{pad}  source_any: None,")
    else:
        print(f"{pad}  source_any:")
        print_type(t.source_any, visited, indent + 2)
    print(f"{pad}  missing_import_name: {t.missing_import_name},")
    print(f"{pad}  line: {t.line},")
    print(f"{pad}  column: {t.column},")
    print(f"{pad}{RBRACE}{trailer}")


def print_none_type(
    t: NoneType,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.types.NoneType` type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}NoneType {LBRACE}")
    print(f"{pad}  __id__: #{visited.get(t)},")
    print(f"{pad}  line: {t.line},")
    print(f"{pad}  column: {t.column},")
    print(f"{pad}{RBRACE}{trailer}")


def print_instance_type(
    t: Instance,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.types.Instance` type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}Instance {LBRACE}")
    print(f"{pad}  __id__: #{visited.get(t)},")
    print(f'{pad}  type: TypeInfo("{t.type.fullname}"),')
    print(f"{pad}  args: [")
    for tt in t.args:
        print_type(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    print(f"{pad}  type_ref: {t.type_ref},")
    print(f"{pad}  line: {t.line},")
    print(f"{pad}  column: {t.column},")
    if t.last_known_value is None:
        print(f"{pad}  last_known_value: None,")
    else:
        print(f"{pad}  last_known_value:")
        print_type(t.last_known_value, visited, indent + 2)
    print(f"{pad}  extra_attrs: {t.extra_attrs!r},")
    print(f"{pad}  can_be_true: {t.can_be_true},")
    print(f"{pad}  can_be_false: {t.can_be_false},")
    print(f"{pad}{RBRACE}{trailer}")


def print_callable_type(
    t: CallableType,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.types.CallableType` type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}CallableType {LBRACE}")
    print(f"{pad}  __id__: #{visited.get(t)},")
    print(f"{pad}  arg_types: [")
    for tt in t.arg_types:
        print_type(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    print(f"{pad}  arg_kinds: {t.arg_kinds},")
    print(f"{pad}  arg_names: {t.arg_names},")
    print(f"{pad}  ret_type:")
    print_type(t.ret_type, visited, indent + 2)
    print(f"{pad}  fallback:")
    print_type(t.fallback, visited, indent + 2)
    print(f"{pad}  name: {t.name},")
    if t.definition is None:
        print(f"{pad}  definition: None,")
    else:
        print(f"{pad}  definition:")
        print_node(t.definition, visited, indent + 2)
    print(f"{pad}  variables: [")
    for tt in t.variables:
        print_type(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    print(f"{pad}  line: {t.line},")
    print(f"{pad}  column: {t.column},")
    print(f"{pad}  is_ellipsis_args: {t.is_ellipsis_args},")
    print(f"{pad}  implicit: {t.implicit},")
    print(f"{pad}  special_sig: {t.special_sig},")
    print(f"{pad}  from_type_type: {t.from_type_type},")
    print(f"{pad}  is_bound: {t.is_bound},")
    if t.type_guard is None:
        print(f"{pad}  type_guard: None,")
    else:
        print(f"{pad}  type_guard:")
        print_type(t.type_guard, visited, indent + 2)
    if t.type_is is None:
        print(f"{pad}  type_is: None,")
    else:
        print(f"{pad}  type_is:")
        print_type(t.type_is, visited, indent + 2)
    print(f"{pad}  from_concatenate: {t.from_concatenate},")
    print(f"{pad}  imprecise_arg_kinds: {t.imprecise_arg_kinds},")
    print(f"{pad}  unpack_kwargs: {t.unpack_kwargs},")
    if t.instance_type is None:
        print(f"{pad}  instance_type: None,")
    else:
        print(f"{pad}  instance_type:")
        print_type(t.instance_type, visited, indent + 2)
    print(f"{pad}{RBRACE}{trailer}")


def print_tuple_type(
    t: TupleType,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.types.TupleType` type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}TupleType {LBRACE}")
    print(f"{pad}  __id__: #{visited.get(t)},")
    print(f"{pad}  items: [")
    for tt in t.items:
        print_type(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    print(f"{pad}  partial_fallback:")
    print_type(t.partial_fallback, visited, indent + 2)
    print(f"{pad}  implicit: {t.implicit},")
    print(f"{pad}  line: {t.line},")
    print(f"{pad}  column: {t.column},")
    print(f"{pad}{RBRACE}{trailer}")


def print_union_type(
    t: UnionType,
    visited: Visited,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a :class:`mypy.types.UnionType` type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    """
    pad = INDENTATION_BLOCK * indent
    print(f"{pad}UnionType {LBRACE}")
    print(f"{pad}  __id__: #{visited.get(t)},")
    print(f"{pad}  items: [")
    for tt in t.items:
        print_type(tt, visited, indent + 2, ",")
    print(f"{pad}  ],")
    print(f"{pad}  is_evaluated: {t.is_evaluated},")
    print(f"{pad}  uses_pep604_syntax: {t.uses_pep604_syntax},")
    print(f"{pad}  original_str_expr: {t.original_str_expr},")
    print(f"{pad}  original_str_fallback: {t.original_str_fallback},")
    print(f"{pad}  line: {t.line},")
    print(f"{pad}  column: {t.column},")
    print(f"{pad}{RBRACE}{trailer}")


def print_type(
    t: Type,
    visited: Visited | None = None,
    indent: int = 0,
    trailer: str = "",
) -> None:
    """
    Print a type.

    :param t: The type
    :param visited: The registry tracking visited objects
    :param indent: The indentation level
    :param trailer: The trailing characters to be printed
    :raises TypeError: when an unknown type is tried to be printed
    """
    if visited is None:
        visited = Visited()
    if visited.contains(t):
        pad = INDENTATION_BLOCK * indent
        print(
            f"{pad}{t.__class__.__name__} {LBRACE}"
            f"[[visited @ #{visited.get(t)}]], ..."
            f"{RBRACE}{trailer}"
        )
        return
    visited.add(t)

    if isinstance(t, TypeAliasType):
        print_typealias_type(t, visited, indent, trailer)
    elif isinstance(t, TypeVarType):
        print_typevar_type(t, visited, indent, trailer)
    elif isinstance(t, ParamSpecType):
        print_paramspec_type(t, visited, indent, trailer)
    elif isinstance(t, AnyType):
        print_any_type(t, visited, indent, trailer)
    elif isinstance(t, NoneType):
        print_none_type(t, visited, indent, trailer)
    elif isinstance(t, Instance):
        print_instance_type(t, visited, indent, trailer)
    elif isinstance(t, CallableType):
        print_callable_type(t, visited, indent, trailer)
    elif isinstance(t, TupleType):
        print_tuple_type(t, visited, indent, trailer)
    elif isinstance(t, UnionType):
        print_union_type(t, visited, indent, trailer)
    else:
        raise TypeError(f"Unknown type: {t.__class__.__name__}")
