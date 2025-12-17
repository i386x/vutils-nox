#
# File:    ./noxfile.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-11-03 02:01:49 +0100
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
# /// script
# dependencies = ["nox", "pkginfo", "pydantic", "setuptools", "tomli_w"]
# ///
"""The Noxfile."""

from vutils.nox.nox import setup


setup()
