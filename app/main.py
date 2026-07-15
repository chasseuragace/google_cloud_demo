import logging

from fastapi import FastAPI

from app.api.v1.routes.issues import router as issues_router
from app.core.logging import configure_logging
from app.db.schema import init_schema_with_retry

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Issues API")
app.include_router(issues_router)


@app.on_event("startup")
def on_startup() -> None:
    init_schema_with_retry()

