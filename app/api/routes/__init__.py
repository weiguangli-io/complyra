from fastapi import APIRouter

from app.api.routes import auth, chat, documents, ingest, audit, health, approvals, tenants, users


api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(ingest.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(audit.router)
api_router.include_router(approvals.router)
api_router.include_router(tenants.router)
api_router.include_router(users.router)
api_router.include_router(health.router)
