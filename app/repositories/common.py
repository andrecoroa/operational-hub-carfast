from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")


def get_by_id(db: Session, model: type[ModelT], object_id: int) -> ModelT | None:
    return db.get(model, object_id)


def get_by_code(db: Session, model: type[ModelT], code: str) -> ModelT | None:
    return db.scalar(select(model).where(model.code == code))

