#
# File:    ./src/vutils/nox/sessions.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-01 03:08:53 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""Predefined sessions, commands, and configuration."""

from typing import TYPE_CHECKING

from vutils.nox.command import KW_ENVNAME, KW_NAME
from vutils.nox.utils import inside_ci, project_pythons, KW_PYTHON

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence, Unpack
    from typing import Generator

    from vutils.nox import MatrixArgs

#: Run linters, recreate environment tag
LINT_R_TAG: str = "lint-r"
#: Run linters, reuse environment tag
LINT_TAG: str = "lint"
#: Run tests tag
TESTS_TAG: str = "tests"

#: :obj:`True` if we are running inside CI
INSIDE_CI: bool = inside_ci()
#: All supported Python versions by the project. In CI, this is provided by the
#: test matrix, defined inside CI, and hence we pass the empty list here
ALL_PYTHONS: Sequence[str] = project_pythons() if not INSIDE_CI else []


def pyvers(pythons: Iterable[str]) -> Generator[tuple[str, str]]:
    """
    Create a generator that yields Python versions pairs.

    :param pythons: The list of Python versions
    :return: the generator yielding a pair containing a Python version from
        :xarg:`pythons` and the same version with the dot (``.``) separators
        removed
    """
    pyver: str
    for pyver in pythons:
        yield (pyver, pyver.replace(".", ""))


def ci_matrix(**exts: Unpack(MatrixArgs)) -> Generator[MatrixArgs]:
    """
    Create a test matrix for CI.

    :param exts: The test matrix overrides
    :return: the test matrix

    Most CIs have their own ways of specifying test matrices and supplying
    Python virtual environments as part of them so we can just use the same
    version of Python that was used to run the Nox.
    """
    matrix: MatrixArgs = {KW_ENVNAME: KW_PYTHON, KW_PYTHON: KW_PYTHON}
    matrix.update(exts)
    yield matrix


def purge_matrix(pythons: Iterable[str]) -> Generator[MatrixArgs]:
    """
    """
    for pyver, ver in pyvers(pythons):
        yield {
            KW_NAME: f"pu{ver}",
            "envname": f"py{ver}",
            "description": f"Purge `py{ver}` environment",
            "python": pyver,
            "tags": [KW_TESTS, f"t{ver}"],
        }
    yield from default_matrix(tags=[KW_TESTS, KW_LINT_R])


@add(matrix=purge_matrix(ALL_PYTHONS), reuse_venv=False, default=True)
class Purge(Command):
    """Purge Python environment."""

    __slots__ = ()

    def run(self, session):
        """"""
        dist_dir = resolve_path(".") / "dist"
        if dist_dir.is_dir():
            shutil.rmtree(dist_dir, ignore_errors=True)


@add(
    envname=KW_PYTHON,
    python=KW_PYTHON,
    reuse_venv=True,
    default=True,
    tags=[KW_TESTS],
)
class Build(Command):
    """Build the package."""

    __slots__ = ()

    def run(self, session):
        """"""
        dist_dir = resolve_path(".") / "dist"
        if not dist_dir.is_dir():
            session.run("python", "-m", "build")


def audit_matrix(pythons):
    for pyver, ver in pyvers(pythons):
        yield {
            "name": f"pa{ver}",
            "envname": f"py{ver}",
            "description": f"Audit `py{ver}` for vulnerabilities",
            "python": pyver,
        }
    if not pythons:
        yield from default_matrix()


@dep("pip-audit")
@add(matrix=audit_matrix(ALL_PYTHONS), reuse_venv=True, default=False)
class Audit(Command):
    """Audit Python environment for vulnerabilities."""

    __slots__ = ()

    def run(self, session):
        """"""
        session.run("python", "-m", "pip_audit", "--progress-spinner", "off")


def pytest_matrix(pythons):
    for pyver, ver in pyvers(pythons):
        yield {
            "name": f"py{ver}",
            "envname": f"py{ver}",
            "description": f"Run unit tests for `py{ver}`",
            "python": pyver,
        }
    if not pythons:
        yield from default_matrix()


@dep(".")
@dep("pytest")
@dep("pytest-cov")
@dep("vutils-testing")
@add(matrix=pytest_matrix(ALL_PYTHONS), reuse_venv=True, default=False)
class Pytest(Command):
    """Run unit tests."""

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


def coveralls_matrix(pythons):
    for pyver, ver in pyvers(pythons):
        yield {
            "name": f"cov{ver}",
            "envname": f"py{ver}",
            "description": f"Report code coverage for `py{ver}`"
            "python": pyver,
        }
    if not pythons:
        yield from default_matrix()


@dep("coveralls")
@add(matrix=coveralls_matrix(ALL_PYTHONS), reuse_venv=True, default=False)
class Coveralls(Command):
    """Report code coverage."""

    __slots__ = ()

    def run(self, session):
        """"""
        args = ["coveralls"]
        if INSIDE_CI:
            basedir = relative_path(packages_dir(session, self.package))
            args.extend([f"--basedir={basedir}", "--srcdir=src"])
        else:
            args.append(f"--output={self.envname}-coverage.txt")
        session.run(*args)


def test_matrix(pythons):
    for pyver, ver in pyvers(pythons):
        yield {
            "actions": [f"pa{ver}", f"py{ver}", f"cov{ver}"],
            "name": f"test{ver}",
            "envname": f"py{ver}",
            "description": f"Run tests for py{ver}",
            "python": pyver,
        }


@dep("./dist")
@add(
    matrix=test_matrix(ALL_PYTHONS),
    reuse_venv=True,
    default=True,
    tags=[KW_TESTS],
)
class Test(Command):
    """Run tests."""


@dep("black")
@cfg("line-length", 79)
class Black(Command):
    """"""

    __slots__ = ()

    def run(self, session):
        """"""
        session.run("black", "--config", self.config(f"{self.name}.toml"))
