from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Created only by server authentication or explicit test dependency overrides."""

    actor_id: UUID
    permissions: frozenset[str]
    request_id: UUID
