"""Códigos de domínio estáveis. O banco guarda o CÓDIGO; a UI traduz.

Nunca renomeie um valor destes: é chave de integração e de i18n.
"""

from enum import StrEnum


class VisitState(StrEnum):
    EXPECTED = "expected"          # agendado/anunciado, ainda fora
    AT_GATE_IN = "at_gate_in"      # na guarita de entrada, em triagem
    IN_YARD = "in_yard"            # liberado, ocupando vaga
    AT_DOCK = "at_dock"            # posicionado em doca
    AT_GATE_OUT = "at_gate_out"    # na guarita de saída
    DEPARTED = "departed"          # saiu
    REJECTED = "rejected"          # recusado na triagem


OPEN_STATES = (
    VisitState.AT_GATE_IN,
    VisitState.IN_YARD,
    VisitState.AT_DOCK,
    VisitState.AT_GATE_OUT,
)

# Máquina de estados do veículo em pátio. Transição fora daqui é erro de domínio.
TRANSITIONS: dict[VisitState, tuple[VisitState, ...]] = {
    VisitState.EXPECTED: (VisitState.AT_GATE_IN, VisitState.REJECTED),
    VisitState.AT_GATE_IN: (VisitState.IN_YARD, VisitState.REJECTED),
    VisitState.IN_YARD: (VisitState.AT_DOCK, VisitState.AT_GATE_OUT),
    VisitState.AT_DOCK: (VisitState.IN_YARD, VisitState.AT_GATE_OUT),
    VisitState.AT_GATE_OUT: (VisitState.DEPARTED, VisitState.IN_YARD),
    VisitState.DEPARTED: (),
    VisitState.REJECTED: (),
}


class OperationDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    TRANSIT = "transit"


class SlotKind(StrEnum):
    PARKING = "parking"
    STAGING = "staging"
    QUARANTINE = "quarantine"
    SCALE_QUEUE = "scale_queue"
    DOCK_APPROACH = "dock_approach"
    # Alimentos: carreta refrigerada espera ligada na tomada; vaga comum não serve.
    COLD_CHAIN = "cold_chain"


class SlotStatus(StrEnum):
    AVAILABLE = "available"
    BLOCKED = "blocked"
    MAINTENANCE = "maintenance"


class VehicleKind(StrEnum):
    TRUCK = "truck"
    TRUCK_TRAILER = "truck_trailer"
    VAN = "van"
    CONTAINER_CHASSIS = "container_chassis"
    TANKER = "tanker"


class DockStatus(StrEnum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    BLOCKED = "blocked"


class EventType(StrEnum):
    GATE_IN = "gate_in"
    GATE_OUT = "gate_out"
    SLOT_ASSIGNED = "slot_assigned"
    SLOT_RELEASED = "slot_released"
    DOCK_ASSIGNED = "dock_assigned"
    DOCK_RELEASED = "dock_released"
    STATE_CHANGED = "state_changed"
    REJECTED = "rejected"
    NOTE = "note"


class EventSource(StrEnum):
    MANUAL = "manual"       # digitado por humano
    DEVICE = "device"       # LPR, balança, cancela, sensor
    SIMULATOR = "simulator"  # simulador de campo
    SYSTEM = "system"       # regra automática
    AI_CONFIRMED = "ai_confirmed"  # sugestão de IA confirmada por humano
