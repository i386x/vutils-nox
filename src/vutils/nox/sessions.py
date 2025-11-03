#
# File:    ./src/vutils/nox/sessions.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-01 03:08:53 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Predefined sessions, commands, and configuration."""




[testenv]
passenv = *
description =
    {envname}: Run unit tests for {envname}
deps =
    idna >=3.7
    pip-audit
    pytest
    pytest-cov
    vutils-testing
    vutils-yaml
    coveralls
allowlist_externals =
    bash
    rm
install_command =
    bash -c '\
      python -I -m pip install -U \
        "requests >=2.32.0" \
        "pip >=23.3" \
        "setuptools >=65.5.1" \
        "wheel >=0.38.1"; \
      python -I -m pip install "$@" \
    ' -- {opts} {packages}
commands =
    python -m pip_audit --progress-spinner off
    pytest -v --cov=sphinx_abcdoc_theme --cov-report=term-missing tests
    {env:COVERALLS_CMD:coveralls --output={envname}-coverage.txt}

__DEPENDENCIES = {
    "test": {
        "idna": Security(">=3.7"),
        ".": LocalDist(path="./dist", kind=DistKind.BDIST),
    },
    "pytest": {
        ".": LocalDist(),
        "pytest": "",
        "pytest-cov": "",
        "vutils-testing": "",
    },
}
__CONFIGURATIONS = {
    "black.toml": {
        "line-length": 79,
    },
}

@dep(".")
@dep("pytest")
@dep("pytest-cov")
@dep("vutils-testing")
class Pytest(Command):
    """"""

    __slots__ = ()

    def run(self, session):
        """"""
        session.run(
            "pytest",
            "-v",
            f"--cov={self.package}",
            "--cov-report=term-missing",
            "tests",
        )


class Test(Command):
    """"""

    def __init__(self, name=None, doc=None):
        Command.__init__(name, doc, zzz)

@dep("black")
@cfg("line-length", 79)
class Black(Command):
    """"""

    __slots__ = ()

    def run(self, session):
        """"""
        session.run("black", "--config", self.config(f"{self.name}.toml"))


def generate_test_sessions(pythons):
    """"""
    for python in pythons:
        command =


def test(session, mode):
    update_when_needed(session, ["pip-audit", "pytest", "pytest-cov", "vutils-testing"])
    install_wheel(session)
    pip_audit(session)
    pytest(session)
