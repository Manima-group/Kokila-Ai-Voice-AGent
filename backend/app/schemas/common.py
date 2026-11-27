from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel):
    items: list[Any]
    total: int
    limit: int
    offset: int


def paginate(db: Session, stmt: Select, limit: int, offset: int, schema: type[BaseModel]) -> Page:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    return Page(items=[schema.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)
