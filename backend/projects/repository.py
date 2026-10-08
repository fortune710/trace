"""Project persistence boundary.

The extracted service is the compatibility implementation for now.  Keeping
this module independent of FastAPI makes the repository boundary explicit and
gives the next extraction step a stable home for SQLAlchemy queries.
"""

from resources.services import ProjectService as ProjectRepository

__all__ = ["ProjectRepository"]
