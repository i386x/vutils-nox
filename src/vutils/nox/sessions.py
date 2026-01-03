#
# File:    ./src/vutils/nox/sessions.py
# Author:  Jiří Kučera <sanczes AT gmail.com>
# Date:    2025-10-01 03:08:53 +0200
# Project: vutils-nox: Shared Nox configuration for vutils
#
# SPDX-License-Identifier: MIT
#
"""
Predefined sessions, commands, and configurations.

CI workflow:

* Purge:
  * create new environment
  * upgrade ``pip`` if necessary
  * remove ``./dist``
* Build:
  * build wheel
* Install:
  * install wheel
* Test:
  * run tests
* Coverage:
  * report coverage to ``coveralls.io``
* Audit:
  * audit environment
  * audit dependencies from the installed packages dump, e.g. produced by
    ``pip freeze``
* Uninstall:
  * uninstall wheel
* Setenv:
  * set ``PYTHONPATH=./src`` for linters
* Check:
  * audit local project
  * check MANIFEST
  * check wheel using ``twine check --strict``
* Run linters
* Build docs
* Audit:
  * audit environment
  * audit dependencies from the installed packages dump, e.g. produced by
    ``pip freeze``

Local workflow:

* Purge:
  * create new environment [pyXY, python]
  * upgrade ``pip`` if necessary [pyXY, python]
  * remove ``./dist``
* Build:
  * build wheel [python]
* Install:
  * requires: Build
  * install wheel [pyXY]
* Test:
  * run tests [pyXY]
* Coverage:
  * report coverage to a text file [pyXY]
* Audit:
  * audit environment [pyXY]
  * audit dependencies from the installed packages dump, e.g. produced by
    ``pip freeze`` [pyXY]
* Uninstall:
  * uninstall wheel [pyXY]
* Setenv:
  * set ``PYTHONPATH=./src`` for linters [python]
* Check:
  * audit local project [python]
  * check MANIFEST [python]
  * check wheel using ``twine check --strict`` [python]
* Run linters [python, mypy: pyXY]
* Build docs [python]
* Audit:
  * audit environment [pyXY, python]
  * audit dependencies from the installed packages dump, e.g. produced by
    ``pip freeze`` [pyXY, python]

"""

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Generator, Unpack

from nox.sessions import Session

from vutils.nox.command import (
    KW_ACTIONS,
    KW_DESCRIPTION,
    KW_ENVNAME,
    KW_NAME,
    Command,
    CommandState,
)
from vutils.nox.decorators import add, cfg, dep, KW_TAGS
from vutils.nox.utils import (
    dist_dir,
    inside_ci,
    packages_dir,
    project_pythons,
    relative_path,
    remove_build_artifacts,
    rm_dist_dir,
    upgrade_pip,
    KW_PYTHON,
)

if TYPE_CHECKING:
    from collections.abc import MutableSequence
    import os

    from vutils.nox import MatrixArgs, StrPath

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


def pyvers(pythons: Iterable[str]) -> Generator[tuple[str, str], None, None]:
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


def ci_matrix(
    **exts: Unpack["MatrixArgs"],
) -> Generator["MatrixArgs", None, None]:
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


@add(matrix=ci_matrix(), reuse_venv=True, default=False)
class Dummy(Command):
    """Dummy command."""

    __slots__ = ()


def purge_matrix(
    pythons: Iterable[str],
) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`~.Purge` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
    pyver: str
    ver: str
    for pyver, ver in pyvers(pythons):
        yield {
            KW_NAME: f"pu{ver}",
            KW_ENVNAME: f"py{ver}",
            KW_DESCRIPTION: f"Purge `py{ver}` environment",
            KW_PYTHON: pyver,
            KW_TAGS: [TESTS_TAG, f"t{ver}"],
        }
    yield from ci_matrix(tags=[TESTS_TAG, LINT_R_TAG])


@add(matrix=purge_matrix(ALL_PYTHONS), reuse_venv=False, default=True)
class Purge(Command):
    """Purge Python environment."""

    __slots__ = ()

    def run(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Perform the purge.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not
        """
        rm_dist_dir()
        remove_build_artifacts()
        upgrade_pip(session)


@add(matrix=ci_matrix(), reuse_venv=True, default=True, tags=[TESTS_TAG])
@dep("build")
class Build(Command):
    """Build the package."""

    __slots__ = ()

    def run(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Perform the package build.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not
        """
        if not dist_dir().is_dir():
            session.run(KW_PYTHON, "-m", "build")
        remove_build_artifacts()


def audit_matrix(
    pythons: Iterable[str],
) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`~.Audit` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
    pyver: str
    ver: str
    for pyver, ver in pyvers(pythons):
        yield {
            KW_NAME: f"pa{ver}",
            KW_ENVNAME: f"py{ver}",
            KW_DESCRIPTION: f"Audit `py{ver}` for vulnerabilities",
            KW_PYTHON: pyver,
        }
    if not pythons:
        yield from ci_matrix()


@add(matrix=audit_matrix(ALL_PYTHONS), reuse_venv=True, default=False)
@dep("pip-audit")
class Audit(Command):
    """Audit Python environment for vulnerabilities."""

    __slots__ = ()

    def run(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Perform the audit.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not
        """
        session.run(KW_PYTHON, "-m", "pip_audit", "--progress-spinner", "off")


def pytest_matrix(
    pythons: Iterable[str],
) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`~.Pytest` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
    pyver: str
    ver: str
    for pyver, ver in pyvers(pythons):
        yield {
            KW_NAME: f"py{ver}",
            KW_ENVNAME: f"py{ver}",
            KW_DESCRIPTION: f"Run unit tests for `py{ver}`",
            KW_PYTHON: pyver,
        }
    if not pythons:
        yield from ci_matrix()


@add(matrix=pytest_matrix(ALL_PYTHONS), reuse_venv=True, default=False)
@dep("vutils-testing")
@dep("pytest-cov")
@dep("pytest")
@dep(".")
class Pytest(Command):
    """Run unit tests."""

    __slots__ = ()

    def run(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Run unit tests.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not
        """
        session.run(
            "pytest",
            "-v",
            f"--cov={self.package}",
            "--cov-report=term-missing",
            "tests",
        )


def coveralls_matrix(
    pythons: Iterable[str],
) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`~.Coveralls` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
    pyver: str
    ver: str
    for pyver, ver in pyvers(pythons):
        yield {
            KW_NAME: f"cov{ver}",
            KW_ENVNAME: f"py{ver}",
            KW_DESCRIPTION: f"Report code coverage for `py{ver}`",
            KW_PYTHON: pyver,
        }
    if not pythons:
        yield from ci_matrix()


@add(matrix=coveralls_matrix(ALL_PYTHONS), reuse_venv=True, default=False)
@cfg("report::exclude_also", ["^if TYPE_CHECKING:$"])
@dep("coveralls")
class Coveralls(Command):
    """Report code coverage."""

    __slots__ = ()

    def run(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Report code coverage.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not
        """
        coveragerc: StrPath | None = self.config(".coveragerc")
        args: MutableSequence[str] = ["coveralls", f"--rcfile={coveragerc}"]
        if INSIDE_CI:
            basedir: os.PathLike[str] = relative_path(
                packages_dir(session, self.package)
            )
            args.extend([f"--basedir={basedir}", "--srcdir=src"])
        else:
            args.append(f"--output={self.envname}-coverage.txt")
        session.run(*args)


def test_matrix(pythons: Iterable[str]) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`~.Test` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
    pyver: str
    ver: str
    for pyver, ver in pyvers(pythons):
        yield {
            KW_ACTIONS: [f"pa{ver}", f"py{ver}", f"cov{ver}"],
            KW_NAME: f"test{ver}",
            KW_ENVNAME: f"py{ver}",
            KW_DESCRIPTION: f"Run tests for py{ver}",
            KW_PYTHON: pyver,
        }
    if not pythons:
        yield from ci_matrix(actions=["audit", "pytest", "coveralls"])


@add(
    matrix=test_matrix(ALL_PYTHONS),
    reuse_venv=True,
    default=True,
    tags=[TESTS_TAG],
    requires=["build"],
)
@dep("./dist")
class Test(Command):
    """Run tests."""

    __slots__ = ()


@add(
    matrix=ci_matrix(),
    reuse_venv=True,
    default=True,
    tags=[LINT_TAG, LINT_R_TAG],
)
@cfg("tool::black::line-length", 79)
@dep("black")
class Black(Command):
    """Run formatting checks."""

    __slots__ = ()

    def run(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Run formatting checks.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not
        """
        session.run(
            "black",
            "--config",
            self.config(f"{self.name}.toml"),
            "--check",
            "--diff",
            ".",
        )
