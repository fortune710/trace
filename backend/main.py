from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db.session import get_engine, get_redis_url


app = FastAPI(title="Trace API")


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "Trace API is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", response_model=None)
def readiness_check():
    try:
        get_redis_url()
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except (RuntimeError, SQLAlchemyError):
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "unavailable"})

    return {"status": "ok"}
