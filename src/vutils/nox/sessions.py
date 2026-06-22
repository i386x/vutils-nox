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

import tempfile
from collections.abc import Iterable, MutableSequence, Sequence
from typing import TYPE_CHECKING, Generator, Unpack

from nox.sessions import Session

from vutils.nox.command import (
    KW_ACTIONS,
    KW_DESCRIPTION,
    KW_ENVNAME,
    KW_NAME,
    Command,
    find_package,
)
from vutils.nox.decorators import KW_REQUIRES, KW_TAGS, add, cfg, dep
from vutils.nox.pkgspec import KW_ALL, LocalDist
from vutils.nox.project import project_name, project_pythons
from vutils.nox.utils import (
    DANGER_ENV_VARS,
    DIST_DIR_NAME,
    EV_PYTHONPATH,
    KW_PYTHON,
    dist_dir,
    inside_ci,
    packages_dir,
    project_dirs,
    relative_path,
    remove_build_artifacts,
    rm_dist_dir,
    setenv,
    src_dir,
    upgrade_pip,
)

if TYPE_CHECKING:
    from vutils.nox import MatrixArgs

#: Run the check subset of linters
CHECK_TAG = "check"
#: Run linters, recreate environment tag
LINT_R_TAG = "lint-r"
#: Run linters, reuse environment tag
LINT_TAG = "lint"
#: Run tests tag
TESTS_TAG = "tests"

#: :obj:`True` if we are running inside CI
INSIDE_CI = inside_ci()
#: All supported Python versions by the project. In CI, this is provided by the
#: test matrix, defined inside CI, and hence we pass the empty list here
ALL_PYTHONS: Iterable[str] = project_pythons() if not INSIDE_CI else []

#: Common configuration constants
LINE_LENGTH = 79


def package_name() -> str:
    """
    Return the importable package name for this project.

    :return: the importable package name
    :raises ValueError: when the project does not ship importable package
    """
    package = find_package()
    if package is None:
        raise ValueError("The project does not ship any importable package")
    return package


def pyvers(pythons: Iterable[str]) -> Generator[tuple[str, str], None, None]:
    """
    Create a generator that yields Python versions pairs.

    :param pythons: The list of Python versions
    :return: the generator yielding a pair containing a Python version from
        :xarg:`pythons` and the same version with the dot (``.``) separators
        removed
    """
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
    matrix = {KW_ENVNAME: KW_PYTHON, KW_PYTHON: KW_PYTHON}
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
    Create a test matrix for :class:`.Purge` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
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


def build_matrix(
    pythons: Iterable[str],
) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`.Build` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
    tags = [TESTS_TAG]
    tags.extend(f"t{ver}" for _, ver in pyvers(pythons))
    yield from ci_matrix(tags=tags)


@add(matrix=build_matrix(ALL_PYTHONS), reuse_venv=True, default=True)
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


def pytest_matrix(
    pythons: Iterable[str],
) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`.Pytest` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
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
    Create a test matrix for :class:`.Coveralls` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
    for pyver, ver in pyvers(pythons):
        yield {
            KW_NAME: f"cov{ver}",
            KW_ENVNAME: f"py{ver}",
            KW_DESCRIPTION: f"Report code coverage for `py{ver}`",
            KW_PYTHON: pyver,
            KW_REQUIRES: [f"py{ver}"],
        }
    if not pythons:
        yield from ci_matrix(requires=["pytest"])


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
        coveragerc = self.config(".coveragerc")
        args = ["coveralls", f"--rcfile={coveragerc}"]
        if INSIDE_CI:
            basedir = relative_path(packages_dir(session, self.package))
            args.extend(
                [
                    f"--basedir={basedir}",
                    f"--srcdir={relative_path(src_dir())}",
                ],
            )
        else:
            args.append(f"--output={self.envname}-coverage.txt")
        session.run(*args)


def audit_matrix(
    pythons: Iterable[str],
) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`.Audit` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete_on_close=False
        ) as fobj:
            fobj.write(
                session.run(
                    KW_PYTHON,
                    "-m",
                    "pip",
                    "freeze",
                    "--all",
                    silent=True,
                    log=False,
                ).strip()
            )
            fobj.close()
            session.run(
                KW_PYTHON,
                "-m",
                "pip_audit",
                "--progress-spinner",
                "off",
                "-r",
                fobj.name,
            )


def test_matrix(pythons: Iterable[str]) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`.Test` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
    for pyver, ver in pyvers(pythons):
        yield {
            KW_ACTIONS: [f"py{ver}", f"cov{ver}", f"pa{ver}"],
            KW_NAME: f"test{ver}",
            KW_ENVNAME: f"py{ver}",
            KW_DESCRIPTION: f"Run tests for `py{ver}`",
            KW_PYTHON: pyver,
            KW_TAGS: [TESTS_TAG, f"t{ver}"],
        }
    if not pythons:
        yield from ci_matrix(
            actions=["pytest", "coveralls", "audit"], tags=[TESTS_TAG]
        )


@add(
    matrix=test_matrix(ALL_PYTHONS),
    reuse_venv=True,
    default=True,
    requires=["build"],
)
@dep(f"./{DIST_DIR_NAME}")
class Test(Command):
    """Run tests."""

    __slots__ = ()


def uninstall_matrix(
    pythons: Iterable[str],
) -> Generator["MatrixArgs", None, None]:
    """
    Create a test matrix for :class:`.Uninstall` command.

    :param pythons: Supported Python versions
    :return: the test matrix
    """
    for pyver, ver in pyvers(pythons):
        yield {
            KW_NAME: f"uin{ver}",
            KW_ENVNAME: f"py{ver}",
            KW_DESCRIPTION: f"Uninstall the package at `py{ver}`",
            KW_PYTHON: pyver,
            KW_TAGS: [TESTS_TAG, f"t{ver}"],
        }
    tags: MutableSequence[str] = [] if pythons else [TESTS_TAG]
    tags.extend([LINT_TAG, LINT_R_TAG])
    yield from ci_matrix(tags=tags)


@add(matrix=uninstall_matrix(ALL_PYTHONS), reuse_venv=True, default=True)
class Uninstall(Command):
    """Uninstall the package."""

    __slots__ = ()

    def run(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Perform the uninstall operation.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not
        """
        with setenv(session, DANGER_ENV_VARS):
            LocalDist().remove(session, KW_ALL)


def linter_matrix(
    xtags: Sequence[str] | None = None,
    prereq: Sequence[str] | None = None,
    postreq: Sequence[str] | None = None,
) -> Generator["MatrixArgs", None, None]:
    """
    Create the common test matrix for linting commands.

    :param xtags: Extra tags
    :param prereq: Priority requirements
    :param postreq: Post requirements
    :return: the test matrix
    """
    tags = [LINT_TAG, LINT_R_TAG]
    if xtags is not None:
        tags.extend(xtags)
    requires: MutableSequence[str] = []
    if prereq is not None:
        requires.extend(prereq)
    requires.extend(["uninstall"])
    if postreq is not None:
        requires.extend(postreq)
    yield from ci_matrix(tags=tags, requires=requires)


class Linter(Command):
    """Linting command base."""

    __slots__ = ()

    def run(self, session: Session, is_subcommand: bool = False) -> None:
        """
        Perform the linting operation.

        :param session: The Nox session
        :param is_subcommand: The flag indicating whether this command is a
            subcommand or not
        """
        with setenv(session, {EV_PYTHONPATH: src_dir()}):
            self.lint(session)

    def lint(self, session: Session) -> None:
        """
        Run the linting command body.

        :param session: The Nox session
        """


@add(
    matrix=linter_matrix(xtags=[CHECK_TAG]),
    name="checkm",
    reuse_venv=True,
    default=True,
)
@dep("check-manifest")
class CheckManifest(Linter):
    """Check the ``MANIFEST.in``."""

    __slots__ = ()

    def lint(self, session: Session) -> None:
        """
        Perform the ``MANIFEST.in`` check.

        :param session: The Nox session
        """
        session.run("check-manifest", ".")


@add(
    matrix=linter_matrix(xtags=[CHECK_TAG], prereq=["build"]),
    name="checkb",
    reuse_venv=True,
    default=True,
)
@dep("twine")
class CheckBuild(Linter):
    """Check the package build."""

    __slots__ = ()

    def lint(self, session: Session) -> None:
        """
        Perform the package build check.

        :param session: The Nox session
        """
        session.run(
            "twine", "check", "--strict", f"{relative_path(dist_dir())}/*"
        )


@add(matrix=linter_matrix(), reuse_venv=True, default=True)
@cfg("tool::black::line-length", LINE_LENGTH)
@dep("black")
class Black(Linter):
    """Run formatting checks."""

    __slots__ = ()

    def lint(self, session: Session) -> None:
        """
        Perform formatting checks.

        :param session: The Nox session
        """
        session.run(
            "black",
            "--config",
            self.config(f"{self.name}.toml"),
            "--check",
            "--diff",
            ".",
        )


@add(matrix=linter_matrix(), reuse_venv=True, default=True)
@cfg(
    "isort",
    {
        "profile": "black",
        "skip_gitignore": True,
        "line_length": LINE_LENGTH,
        "known_first_party": package_name(),
    },
)
@dep("isort")
class Isort(Linter):
    """Run import order checks."""

    __slots__ = ()

    def lint(self, session: Session) -> None:
        """
        Perform import order checks.

        :param session: The Nox session
        """
        session.run(
            "isort",
            "--settings-file",
            self.config(f".{self.name}.cfg"),
            "--diff",
            "-c",
            ".",
        )


#: Patched ``flake8`` compatible with ``black`` plus some additional tweaks
BLACK_COMPAT_FLAKE8 = """
import functools
import re

import flake8.violation

_orig_find_noqa = flake8.violation._find_noqa


def _is_class(line: str) -> bool:
    line = line.strip()
    if line == "): ...":
        # This can also match also an unannotated function but we are taking
        # care of these in `mypy` settings
        return True
    return line.startswith("class ") and line.endswith(": ...")


def _is_func(line: str) -> bool:
    line = line.strip()
    return (
        line.endswith(": ...")
        and (line.startswith("def ") or line.startswith(") -> "))
    )


def _is_import_as_score(line: str) -> bool:
    line = line.strip()
    return line.startswith("import ") and line.endswith(" as _")


@functools.lru_cache(maxsize=512)
def _find_noqa(physical_line: str) -> re.Match[str] | None:
    if physical_line.find("#") >= 0:
        return _orig_find_noqa(physical_line)

    # Catch `E701 multiple statements on one line (colon)` and mark it as
    # `noqa: E701` for `class Foo(...): ...` and `class Foo: ...` cases
    # (demanded by `black`)
    if _is_class(physical_line):
        return _orig_find_noqa(physical_line + " # noqa: E701")
    # Catch `E704 multiple statements on one line (def)` and mark it as
    # `noqa: E704` for the `def foo(...) -> ...: ...` case (demanded by
    # `black`)
    elif _is_func(physical_line):
        return _orig_find_noqa(physical_line + " # noqa: E704")
    # Catch `F401 module imported but unused` and mark it as `noqa: F401` for
    # the `import ... as _` case since such kinds of imports are intentional
    elif _is_import_as_score(physical_line):
        return _orig_find_noqa(physical_line + " # noqa: F401")
    return _orig_find_noqa(physical_line)


flake8.violation._find_noqa = _find_noqa

from flake8.main.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
"""


@add(matrix=linter_matrix(), reuse_venv=True, default=True)
@cfg(
    "flake8",
    {
        "filename": "*.py,*.pyi,*.pyw",
        "select": "E,F,W,C,L,Y,I",
        "enable-extensions": "L,Y,I",
        "max-line-length": LINE_LENGTH,
        "max-doc-length": LINE_LENGTH,
        # Disable not PEP 8 compliant warnings:
        #   E203 whitespace before ':'
        #   W503 line break before binary operator
        # Disable warnings conflicting with black:
        #   E302 expected 2 blank lines, found 0
        "extend-ignore": "E203,E302,W503",
        # Disable warnings conflicting with other linters:
        #   E301 expected 1 blank line, found 0
        #        - disabled for `__init__.pyi` as `black` demands no blank
        #          lines between method stubs
        "per-file-ignores": "__init__.pyi:E301",
        "show-source": True,
        "statistics": True,
        "doctests": True,
        "max-complexity": 15,
        "known-modules": f"{project_name()}:[{package_name()}]",
    },
)
@dep("flake8-requirements")
@dep("flake8-pyi")
@dep("flake8-logging")
@dep("flake8")
class Flake8(Linter):
    """Run style checks."""

    __slots__ = ()

    def lint(self, session: Session) -> None:
        """
        Perform style checks.

        :param session: The Nox session
        """
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="flake8_", suffix=".py", delete_on_close=False
        ) as fobj:
            fobj.write(BLACK_COMPAT_FLAKE8)
            fobj.close()
            session.run(
                KW_PYTHON,
                fobj.name,
                "--config",
                self.config(f".{self.name}.cfg"),
            )


@add(matrix=linter_matrix(), reuse_venv=True, default=True)
@cfg("tool::pylint::similarities::ignore-imports", True)
@cfg(
    "tool::pylint::message control",
    {
        "enable": ["useless-suppression"],
        # `mypy` does the better job
        "disable": ["no-member"],
    },
)
@cfg("tool::pylint::format::max-line-length", LINE_LENGTH)
@cfg("tool::pylint::design::min-public-methods", 0)
@cfg("tool::pylint::main::ignore-patterns", ["^\\.#", "\\.pyi$"])
@dep("%pyproject")
@dep("pytest")
@dep("pylint")
class Pylint(Linter):
    """Run static code checks."""

    __slots__ = ()

    def lint(self, session: Session) -> None:
        """
        Perform static code checks.

        :param session: The Nox session
        """
        dirs = project_dirs(relative=True)
        if len(dirs) == 0:
            return
        args = [
            "pylint",
            "--rcfile",
            self.config(f".{self.name}rc.toml"),
        ]
        args.extend(dirs)
        session.run(*args)


@add(matrix=linter_matrix(), reuse_venv=True, default=True)
@cfg(
    "mypy",
    {
        "mypy_path": "src",
        "disallow_any_unimported": True,
        "disallow_any_expr": True,
        "disallow_any_decorated": True,
        "disallow_any_explicit": True,
        "disallow_any_generics": True,
        "disallow_subclassing_any": True,
        "disallow_untyped_calls": True,
        "disallow_untyped_defs": True,
        "disallow_incomplete_defs": True,
        "check_untyped_defs": True,
        "disallow_untyped_decorators": True,
        "warn_redundant_casts": True,
        "warn_unused_ignores": True,
        "warn_return_any": True,
        "warn_unreachable": True,
        "extra_checks": True,
        "strict_equality": True,
        "strict": True,
        "warn_incomplete_stub": True,
        "warn_unused_configs": True,
    },
)
@dep("%pyproject")
@dep("mypy")
class Mypy(Linter):
    """Run type checks."""

    __slots__ = ()

    def lint(self, session: Session) -> None:
        """
        Perform type checks.

        :param session: The Nox session
        """
        session.run(
            "mypy",
            "--config-file",
            self.config(f".{self.name}.ini"),
            "-p",
            package_name(),
        )
