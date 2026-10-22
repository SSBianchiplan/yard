from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import Role, requires
from app.core.errors import ERR_DUPLICATE, ERR_NOT_FOUND, Conflict, NotFound
from app.modules.catalog import models as m
from app.modules.catalog import schemas as s

router = APIRouter(
    prefix="/catalog",
    tags=["catalog"],
    dependencies=[Depends(requires(Role.ADMIN, Role.SCHEDULER))],
)


def _register(
    path: str, model: type[Any], schema_in: type[Any], schema_out: type[Any], search_field: str
) -> None:
    @router.get(path, response_model=list[schema_out], name=f"list_{path.strip('/')}")
    async def _list(
        session: AsyncSession = Depends(get_session),
        search: str | None = None,
        limit: int = Query(default=500, le=2000),
    ):
        stmt = select(model)
        if search:
            stmt = stmt.where(getattr(model, search_field).ilike(f"%{search}%"))
        stmt = stmt.order_by(getattr(model, search_field)).limit(limit)
        return (await session.execute(stmt)).scalars().all()

    @router.post(path, response_model=schema_out, status_code=201, name=f"create_{path.strip('/')}")
    async def _create(payload: schema_in, session: AsyncSession = Depends(get_session)):  # type: ignore[valid-type]
        obj = model(**payload.model_dump())
        session.add(obj)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise Conflict(ERR_DUPLICATE, entity=model.__tablename__) from exc
        return obj

    @router.patch(path + "/{item_id}", response_model=schema_out, name=f"update_{path.strip('/')}")
    async def _update(
        item_id: UUID, payload: schema_in, session: AsyncSession = Depends(get_session)
    ):  # type: ignore[valid-type]
        obj = (
            await session.execute(select(model).where(model.id == item_id))
        ).scalar_one_or_none()
        if obj is None:
            raise NotFound(ERR_NOT_FOUND, entity=model.__tablename__, id=str(item_id))
        for key, value in payload.model_dump().items():
            setattr(obj, key, value)
        await session.commit()
        return obj


_register("/carriers", m.Carrier, s.CarrierIn, s.CarrierOut, "name")
_register("/drivers", m.Driver, s.DriverIn, s.DriverOut, "full_name")
_register("/vehicles", m.Vehicle, s.VehicleIn, s.VehicleOut, "plate")
_register("/products", m.Product, s.ProductIn, s.ProductOut, "name")
_register("/operation-types", m.OperationType, s.OperationTypeIn, s.OperationTypeOut, "code")
