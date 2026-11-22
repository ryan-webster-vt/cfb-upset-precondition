"""Persistence layer public surface.

Submodules are imported lazily so ``python -m cfb_upset.store.db`` does not
warn about a module that the package __init__ already imported.
"""

from __future__ import annotations

from typing import Any

__all__ = ["Database", "Repositories", "VerifyReport"]


def __getattr__(name: str) -> Any:
    if name in {"Database", "VerifyReport"}:
        from cfb_upset.store import db

        return getattr(db, name)
    if name == "Repositories":
        from cfb_upset.store.repositories import Repositories

        return Repositories
    raise AttributeError(name)
