"""External repository routes are intentionally internal-only.

OAuth callback provisioning is registered by ``auth.oauth``; no public CRUD
router is exposed for provider-account metadata.
"""

from fastapi import APIRouter

router = APIRouter()
