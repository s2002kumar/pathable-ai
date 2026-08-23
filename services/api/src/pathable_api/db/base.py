"""Declarative base for the ORM.

The naming convention matters: Alembic autogenerate produces stable, readable
constraint names from it, so a later migration can drop a constraint by name
instead of by whatever PostgreSQL happened to call it.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for every PathAble ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
