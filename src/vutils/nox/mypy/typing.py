#
# File:    ./src/vutils/nox/mypy/typing.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2026-06-22 23:31:52 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Typing helpers."""


def fix_decorator_type[F](func: F) -> F:
    """
    Help ``mypy`` plugin to fix a decorator type.

    :param func: The decorator function
    :return: the decorator function with fixed signature

    Some libraries may have decorators annotated as
    ``Callable[[Callable[..., T]], Wrapper[T]]``, which is expanded by ``mypy``
    to ``def [T](def (*Any, **Any) -> T) -> Wrapper[T]``, which is adjusted by
    :mod:`.liftany` plugin to
    ``def [T](def (*object, **object) -> T) -> Wrapper[T]``. However, functions
    like ``def (int, float) -> T`` cannot be passed to places where
    ``def (*object, **object) -> T`` is expected, even when this seems to be
    correct, due to the ``mypy`` type checking rules. Thus, when
    ``def (*object, **object) -> ...`` is detected in a decorator signature it
    is replaced with ``def [**P](*P.args, **P.kwargs) -> ...``; in our case:
    ``def [**P, T](def (*P.args, **P.kwargs) -> T) -> Wrapper[T]`` is the final
    type produced by :mod:`.liftany` plugin. To do this conversion properly,
    this function must be used as a wrapper around a decorator function to
    trigger the correct hook provided by :mod:`.liftany` plugin::

        @fix_decorator_type(functools.cache)
        def sum(x: int, y: int) -> int:
            return x + y

    Using the decorator directly is not enough at this time since ``mypy`` does
    not trigger ``get_function_signature_hook`` for decorators.
    """
    return func
