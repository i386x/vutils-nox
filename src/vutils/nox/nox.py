#
# File:    ./src/vutils/nox/nox.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-01 02:30:06 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Nox tweaks."""

from nox.sessions import SessionRunner as NoxSessionRunner

ENVNAME_ATTR = "envname"


class SessionRunner(NoxSessionRunner):
    """"""

    @property
    def envdir(self):
        envname = getattr(self.func, ENVNAME_ATTR, "") or self.friendly_name
        return _normalize_path(self.global_config.envdir, envname)


def fix_registry() -> None:
    """"""
    registry = get()
    for key in registry:
        func = registry[key]
        if hasattr(func, ENVNAME_ATTR):
            continue
        envname = None
        tags = func.tags
        for tag in tags:
            if tag.startswith(":"):
                envname = tag[1:]
                tags.remove(tag)
        if not envname:
            continue
        setattr(func, ENVNAME_ATTR, envname)


def setup():
    """"""
    patch_nox(NoxSessionRunner, SessionRunner)
