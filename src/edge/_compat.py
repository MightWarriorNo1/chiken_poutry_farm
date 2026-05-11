"""Stdlib version shims.

Currently: `StrEnum` for Python < 3.11.

Anything that imports `StrEnum` should go through this module so the domain
code stays version-agnostic. When the minimum supported Python is bumped to
3.11+, delete this file and revert the imports to `from enum import StrEnum`.
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Drop-in for 3.11's `enum.StrEnum`.

        `class Foo(str, Enum)` already covers the cases this project relies on
        (Pydantic v2 serialization, JSON dumping, equality with bare strings).
        The one meaningful gap is `__str__` — 3.11's StrEnum returns the value,
        the plain mix-in returns "ClassName.MEMBER". Patch it for parity so
        f-strings and `str(member)` behave identically across versions.
        """

        def __str__(self) -> str:  # type: ignore[override]
            return str(self.value)


__all__ = ["StrEnum"]
