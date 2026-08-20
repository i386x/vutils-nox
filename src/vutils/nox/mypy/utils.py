#
# File:    ./src/vutils/nox/mypy/utils.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-07-31 07:45:40 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Type handling utilities."""

from collections.abc import Iterable, MutableMapping, MutableSequence, Sequence

from mypy.checker import TypeChecker
from mypy.types import (
    AnyType,
    ParamSpecFlavor,
    ParamSpecType,
    TypeOfAny,
    TypeVarId,
    TypeVarLikeType,
)

#: Cases requiring special care
FIX_DECORATOR_TYPE_FUNC = "vutils.nox.mypy.typing.fix_decorator_type"

#: Names of some important types
DICT_TYPE = "builtins.dict"
OBJECT_TYPE = "builtins.object"
STR_TYPE = "builtins.str"
TUPLE_TYPE = "builtins.tuple"


def verify_type[T](obj: object, typ: type[T]) -> T:
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
    :param namespace: The name space under which the new type variable id
        should belong to
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


class ParamSpec:
    """Parameter specification."""

    #: The bare flavor of the parameter specification
    __bare: ParamSpecType,
    #: The *args* flavor of the parameter specification
    __args: ParamSpecType
    #: The *kwargs* flavor of the parameter specification
    __kwargs: ParamSpecType

    __slots__ = ("__bare", "__args", "__kwargs")

    def __init__(
        self,
        ps_bare: ParamSpecType,
        ps_args: ParamSpecType,
        ps_kwargs: ParamSpecType,
    ) -> None:
        """
        Initialize the parameter specification.

        :param ps_bare: The bare flavor of the parameter specification
        :param ps_args: The *args* flavor of the parameter specification
        :param ps_kwargs: The *kwargs* flavor of the parameter specification
        """
        self.__bare = ps_bare
        self.__args = ps_args
        self.__kwargs = ps_kwargs

    @property
    def bare(self) -> ParamSpecType:
        """
        Get the bare flavor of the parameter specification.

        :return: the bare flavor of the parameter specification
        """
        return self.__bare

    @property
    def args(self) -> ParamSpecType:
        """
        Get the *args* flavor of the parameter specification.

        :return: the *args* flavor of the parameter specification
        """
        return self.__args

    @property
    def kwargs(self) -> ParamSpecType:
        """
        Get the *kwargs* flavor of the parameter specification.

        :return: the *kwargs* flavor of the parameter specification
        """
        return self.__args


class ParamSpecFactory:
    """The parameter specification factory."""

    #: The type checker
    __api: TypeChecker
    #: The parameter specification name space
    __namespace: str
    #: The list of type variables a new parameter specification will belong to
    __variables: MutableSequence[TypeVarLikeType]
    #: The parameter specification storage
    __storage: MutableMapping[str, ParamSpec]

    __slots__ = ("__api", "__namespace", "__variables", "__storage")

    def __init__(
        api: TypeChecker,
        namespace: str,
        variables: Sequence[TypeVarLikeType] | None = None,
    ) -> None:
        """
        Initialize the factory.

        :param api: The type checker
        :param namespace: The parameter specification name space
        :param variables: The list of type variables a new parameter
            specification will belong to
        """
        self.__api = api
        self.__namespace = namespace
        self.__variables = list(variables) if variables else []
        self.__storage = {}

    @property
    def variables(self) -> Sequence[TypeVarLikeType]:
        """
        Get the list of type variables.

        :return: the list of type variables updated about newly created
            parameter specifications
        """
        return self.__variables

    def get(self, name: str) -> ParamSpec:
        """
        Get the parameter specification or create a new one.

        :param name: The name of the parameter specification
        :return: the parameter specification
        """
        if name in self.__storage:
            return self.__storage[name]
        api = self.__api

        tvid = new_typevar_id(self.__variables, self.__namespace)
        ps_bare = new_paramspec(api, name, tvid)
        self.__variables.append(ps_bare)

        ps_args = ps_bare.with_flavor(ParamSpecFlavor.ARGS)
        ps_args.upper_bound = api.named_generic_type(
            TUPLE_TYPE, [api.named_type(OBJECT_TYPE)]
        )

        ps_kwargs = ps_bare.with_flavor(ParamSpecFlavor.KWARGS)
        ps_kwargs.upper_bound = api.named_generic_type(
            DICT_TYPE, [api.named_type(STR_TYPE), api.named_type(OBJECT_TYPE)]
        )

        pspec = ParamSpec(ps_bare, ps_args, ps_kwargs)
        self.__storage[name] = pspec
        return pspec
