from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from contextlib import asynccontextmanager

from core.database import init_db, get_db
from core.logging_config import setup_logging, logger
from core.gcp_auth import configure_google_credentials_from_env
from core.settings import settings
from core.exception_handlers import register_exception_handlers
from routers.rubrics import router as rubrics_router
from routers.evaluations import router as evaluations_router
from routers.file_upload import router as file_upload_router

# 1. Setup Logging (with colorlog!)
setup_logging()

# 2. Define Lifecycle (Startup/Shutdown)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup Logic
    logger.debug("🚀 Starting Evaluator RAG Backend...")
    configure_google_credentials_from_env()
    init_db() 
    yield
    # Shutdown Logic
    logger.debug("🛑 Shutting down Evaluator RAG Backend...")

# 3. Initialize FastAPI
app = FastAPI(
    title=settings.APP_TITLE,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# 4. Register Exception Handlers
register_exception_handlers(app)

# 5. Register API Routers
app.include_router(rubrics_router, prefix=settings.API_V1_PREFIX)
app.include_router(evaluations_router, prefix=settings.API_V1_PREFIX)
app.include_router(file_upload_router)

# 6. Basic Health Check Endpoint
from fastapi import HTTPException

@app.get(settings.HEALTH_CHECK_PATH, tags=["System"])
def health_check(db: Session = Depends(get_db)):
    try:
        # Simple query to verify DB connection is alive
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "database": "disconnected", "error": str(e)})

@app.get(settings.ROOT_PATH, tags=["System"])
def root():
    return {"message": "Welcome to the Evaluador RAG API. Navigate to /docs for Swagger."}
