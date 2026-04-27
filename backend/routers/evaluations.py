"""
Evaluation Router - API endpoints for Evaluation operations.

This module defines the FastAPI router for evaluation-related endpoints,
using dependency injection for both database sessions and service instances.
"""

from typing import List
import hashlib
from fastapi import APIRouter, Depends, status, BackgroundTasks, Header, Request, Response

from core.database import get_db, SQLALCHEMY_DATABASE_URL
from core.settings import settings
from schemas.response import APIResponse
from schemas.evaluation import (
    EvaluationRequest,
    EvaluationResponse,
    EvaluationResponseWithFindings,
)
from services.evaluation_service_api import EvaluationServiceAPI
from services.abuse_protection import guard
from sqlalchemy.orm import Session


# Router configuration
router = APIRouter(
    prefix=settings.EVALUATIONS_ROUTE_PREFIX,
    tags=[settings.EVALUATIONS_TAG],
)

# Common response schemas for OpenAPI documentation
RESPONSE_404 = {
    "description": "Resource not found",
    "content": {
        "application/json": {
            "example": {
                "success": False,
                "data": None,
                "errors": ["Rubric not found"],
                "message": "Rubric not found",
            }
        }
    },
}

RESPONSE_422 = {
    "description": "Validation error",
    "content": {
        "application/json": {
            "example": {
                "success": False,
                "data": None,
                "errors": ["rubric_id: Must be a valid integer"],
                "message": "Validation error",
            }
        }
    },
}


# =============================================================================
# DEPENDENCY INJECTION
# =============================================================================


def get_evaluation_service_api() -> EvaluationServiceAPI:
    """
    Dependency injection provider for EvaluationServiceAPI.

    Returns a new instance of EvaluationServiceAPI for each request,
    following FastAPI's dependency injection pattern.

    Returns:
        EvaluationServiceAPI: A new service instance
    """
    return EvaluationServiceAPI()


def extract_api_key_from_header(
    api_key: str = Header(None, alias="X-API-Key")
):
    """
    Extract API key from X-API-Key header.
    
    Args:
        api_key: API key from X-API-Key header
        
    Returns:
        API key string if provided, None otherwise
    """
    return api_key


def get_client_identity(request: Request) -> str:
    """Build a stable client fingerprint from forwarding headers and user agent."""
    x_forwarded_for = request.headers.get("x-forwarded-for", "")
    forwarded_ip = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else ""
    remote_ip = request.client.host if request.client else "unknown"
    ip = forwarded_ip or remote_ip
    user_agent = request.headers.get("user-agent", "unknown")

    raw = f"{ip}|{user_agent}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{ip}:{digest}"


# =============================================================================
# GET ENDPOINTS
# =============================================================================


@router.get(
    "/",
    response_model=APIResponse[List[EvaluationResponse]],
    summary="List all evaluations",
    description="Retrieve a list of all evaluations without their nested findings.",
    responses={
        422: RESPONSE_422,
    },
)
def list_evaluations(
    db: Session = Depends(get_db),
    evaluation_service: EvaluationServiceAPI = Depends(get_evaluation_service_api),
):
    """
    Retrieve all evaluations from the database.

    Returns a list of evaluations with basic information
    (id, rubric_id, repo_url, status, total_score, ai_summary, created_at).
    Does not include nested findings - use GET /evaluations/{id} for full details.
    """
    return evaluation_service.get_all(db)


@router.get(
    "/{evaluation_id}",
    response_model=APIResponse[EvaluationResponseWithFindings],
    summary="Get evaluation by ID",
    description="Retrieve a single evaluation with all its findings.",
    responses={
        404: RESPONSE_404,
        422: RESPONSE_422,
    },
)
def get_evaluation(
    evaluation_id: int,
    db: Session = Depends(get_db),
    evaluation_service: EvaluationServiceAPI = Depends(get_evaluation_service_api),
):
    """
    Retrieve a specific evaluation by ID with full details.

    Returns the evaluation including all nested findings (WHIS data points).
    Returns an error if the evaluation is not found.
    """
    return evaluation_service.get_by_id(db, evaluation_id)


@router.get(
    "/default-provider/cooldown",
    response_model=APIResponse[dict],
    summary="Get default provider cooldown status",
    description="Returns remaining seconds before Gemini Vertex server-default can be used again.",
)
def get_default_provider_cooldown(
    request: Request,
):
    client_id = get_client_identity(request)
    remaining = guard.get_default_provider_remaining_seconds(
        client_id=client_id,
        cooldown_seconds=settings.DEFAULT_PROVIDER_COOLDOWN_SECONDS,
    )

    return APIResponse(
        success=True,
        data={
            "remaining_seconds": remaining,
            "cooldown_seconds": settings.DEFAULT_PROVIDER_COOLDOWN_SECONDS,
            "available": remaining == 0,
        },
        errors=None,
        message="Cooldown status retrieved",
    )


# =============================================================================
# POST ENDPOINTS
# =============================================================================


@router.post(
    "/",
    response_model=APIResponse[EvaluationResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new evaluation",
    description=(
        "Create a new evaluation for a GitHub repository. "
        "The evaluation is processed in the background - returns immediately with status 'pending'."
    ),
    responses={
        404: {
            "description": "Rubric not found",
            "content": {
                "application/json": {
                    "example": {
                        "success": False,
                        "data": None,
                        "errors": ["Rubric with id 999 not found"],
                        "message": "Rubric not found",
                    }
                }
            },
        },
        422: RESPONSE_422,
    },
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "basic_evaluation": {
                            "summary": "Basic evaluation (no AI configuration)",
                            "description": "Create an evaluation using default AI settings",
                            "value": {
                                "repo_url": "https://github.com/student/backend-project",
                                "rubric_id": 1,
                                "briefing_path": "<FILE_UPLOAD_PATH>/project-briefing.pdf"
                            }
                        },
                        "openai_evaluation": {
                            "summary": "Evaluation with OpenAI configuration",
                            "description": "Create an evaluation using OpenAI GPT-4 (API key via X-API-Key header)",
                            "value": {
                                "repo_url": "https://github.com/student/backend-project",
                                "rubric_id": 1,
                                "briefing_path": "<FILE_UPLOAD_PATH>/project-briefing.pdf",
                                "ai_provider": "openai",
                                "ai_model": "gpt-4"
                            }
                        },
                        "gemini_evaluation": {
                            "summary": "Evaluation with Gemini configuration",
                            "description": "Create an evaluation using Google Gemini (API key via X-API-Key header)",
                            "value": {
                                "repo_url": "https://github.com/student/backend-project",
                                "rubric_id": 1,
                                "briefing_path": "<FILE_UPLOAD_PATH>/project-briefing.pdf",
                                "ai_provider": "gemini",
                                "ai_model": "gemini-1.5-pro"
                            }
                        },
                        "groq_evaluation": {
                            "summary": "Evaluation with Groq configuration",
                            "description": "Create an evaluation using Groq (API key via X-API-Key header)",
                            "value": {
                                "repo_url": "https://github.com/student/backend-project",
                                "rubric_id": 1,
                                "briefing_path": "<FILE_UPLOAD_PATH>/project-briefing.pdf",
                                "ai_provider": "groq",
                                "ai_model": "groq-beta"
                            }
                        }
                    }
                }
            }
        }
    },
)
def create_evaluation(
    request: Request,
    response: Response,
    evaluation_request: EvaluationRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(extract_api_key_from_header),
    db: Session = Depends(get_db),
    evaluation_service: EvaluationServiceAPI = Depends(get_evaluation_service_api),
):
    """
    Create a new evaluation.

    Validates that the rubric exists, processes the briefing PDF for RAG context,
    creates an evaluation record with status 'pending', and queues a background
    task for AI processing.

    The endpoint returns immediately with HTTP 201 and the pending evaluation.
    The actual AI evaluation happens asynchronously in the background.

    Status lifecycle:
    - 'pending': Evaluation created, waiting to be processed
    - 'processing': AI evaluation in progress
    - 'completed': Evaluation finished successfully
    - 'failed': Evaluation encountered an error

    AI Configuration:
    - AI provider, model, and API key can be specified in the request body
    - API key can also be provided via X-API-Key header (recommended for security)
    - If AI configuration is provided, all three fields (provider, model, api_key) must be present
    """
    client_id = get_client_identity(request)

    if settings.ENABLE_EVALUATION_RATE_LIMIT:
        rate_result = guard.check_rate_limit(
            client_id=client_id,
            max_requests=settings.EVALUATION_RATE_LIMIT_MAX_REQUESTS,
            window_seconds=settings.EVALUATION_RATE_LIMIT_WINDOW_SECONDS,
        )
        if not rate_result.allowed:
            response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
            response.headers["Retry-After"] = str(rate_result.retry_after_seconds)
            return APIResponse(
                success=False,
                data=None,
                errors=[
                    f"Rate limit exceeded. Retry in {rate_result.retry_after_seconds} seconds."
                ],
                message="Too many evaluation requests",
            )

    effective_api_key = api_key or evaluation_request.ai_api_key
    uses_server_default_gemini = (
        evaluation_request.ai_provider in (None, "gemini")
        and not effective_api_key
        and settings.VERTEX_ENABLED
    )

    if settings.ENABLE_DEFAULT_PROVIDER_COOLDOWN and uses_server_default_gemini:
        cooldown_result = guard.check_default_provider_cooldown(
            client_id=client_id,
            cooldown_seconds=settings.DEFAULT_PROVIDER_COOLDOWN_SECONDS,
        )
        if not cooldown_result.allowed:
            response.status_code = status.HTTP_429_TOO_MANY_REQUESTS
            response.headers["Retry-After"] = str(cooldown_result.retry_after_seconds)
            return APIResponse(
                success=False,
                data=None,
                errors=[
                    f"Default Gemini Vertex cooldown active. Retry in {cooldown_result.retry_after_seconds} seconds."
                ],
                message="Default provider cooldown active",
            )

    # Merge header API key with request body if AI configuration is provided
    if evaluation_request.ai_provider and evaluation_request.ai_model:
        # Use header API key if provided, otherwise use body API key
        evaluation_request.ai_api_key = effective_api_key

    result = evaluation_service.create(
        db=db,
        evaluation_request=evaluation_request,
        background_tasks=background_tasks,
        db_url=SQLALCHEMY_DATABASE_URL,
    )

    if result.success and uses_server_default_gemini:
        guard.register_default_provider_usage(client_id)

    return result
