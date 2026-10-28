"""Request and response schemas for opaque desktop project handles."""

from uuid import UUID

from resources.schemas import RequestModel


class LocalProjectHandleCreate(RequestModel):
    client_project_id: UUID


class LocalProjectHandleResponse(RequestModel):
    id: UUID
    client_project_id: UUID


__all__ = ["LocalProjectHandleCreate", "LocalProjectHandleResponse"]
