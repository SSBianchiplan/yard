"""Registro único de modelos.

Há FKs cruzando módulos (visit ↔ appointment), então quem precisa do metadata completo
— seeds, testes, alembic — importa daqui em vez de encadear imports entre módulos.
"""

from app.core.db import Base
from app.modules.auth import models as auth
from app.modules.catalog import models as catalog
from app.modules.gate import models as gate
from app.modules.integrations import models as integrations
from app.modules.iot import models as iot
from app.modules.moves import models as moves
from app.modules.scheduling import models as scheduling
from app.modules.tower import models as tower
from app.modules.visits import models as visits
from app.modules.weighing import models as weighing
from app.modules.yard import models as yard

__all__ = ["Base", "auth", "catalog", "gate", "integrations", "iot", "moves", "scheduling", "tower", "visits", "weighing", "yard"]
