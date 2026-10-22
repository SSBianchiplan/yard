from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import OperationDirection, VehicleKind


class Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CarrierIn(BaseModel):
    code: str = Field(max_length=32)
    name: str = Field(max_length=160)
    tax_id: str | None = None
    active: bool = True


class CarrierOut(Read, CarrierIn):
    id: UUID


class DriverIn(BaseModel):
    full_name: str = Field(max_length=160)
    document: str = Field(max_length=32)
    license_number: str | None = None
    license_expires_on: date | None = None
    phone: str | None = None
    carrier_id: UUID | None = None
    active: bool = True


class DriverOut(Read, DriverIn):
    id: UUID


class VehicleIn(BaseModel):
    plate: str = Field(max_length=16)
    trailer_plate: str | None = None
    kind: VehicleKind = VehicleKind.TRUCK
    carrier_id: UUID | None = None
    axles: int | None = None
    tare_kg: int | None = None
    max_gross_kg: int | None = None
    active: bool = True


class VehicleOut(Read, VehicleIn):
    id: UUID


class ProductIn(BaseModel):
    sku: str = Field(max_length=48)
    name: str = Field(max_length=160)
    hazardous: bool = False
    unit: str = "kg"
    active: bool = True


class ProductOut(Read, ProductIn):
    id: UUID


class OperationTypeIn(BaseModel):
    code: str = Field(max_length=32)
    direction: OperationDirection = OperationDirection.INBOUND
    requires_weighing: bool = False
    requires_dock: bool = True
    target_dwell_minutes: int = 90
    notes: str | None = None


class OperationTypeOut(Read, OperationTypeIn):
    id: UUID
