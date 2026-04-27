"""
Evaluation Service API - Business logic for Evaluation operations.

This module provides the service layer for Evaluation CRUD operations,
including the background task for long-running AI evaluation processing.
"""

import json
import os
from typing import List
from sqlalchemy.orm import Session
from fastapi import BackgroundTasks

from models import Evaluation, Rubric
from schemas.response import APIResponse
from schemas.evaluation import EvaluationResponse, EvaluationResponseWithFindings, FindingResponse
from services.pdf_processor import BriefingProcessor
from services.ai_evaluation_engine import AIEvaluationEngine#, run_evaluation_task as ai_run_evaluation_task
from core.logging_config import logger
from core.messages import Messages
from core.database import SessionLocal
from core.settings import AIProvider, settings, get_model, get_api_key


class EvaluationServiceAPI:
    """
    Service class for Evaluation API operations.

    This class encapsulates all business logic related to evaluation management,
    providing a clean interface for CRUD operations with standardized responses.
    """

    def create(
        self,
        db: Session,
        evaluation_request,
        background_tasks: BackgroundTasks,
        db_url: str,
    ) -> APIResponse[EvaluationResponse]:
        """
        Create a new evaluation with processed briefing.

        Validates the rubric exists, processes the briefing PDF, creates
        the evaluation record, and queues the background processing task.

        Args:
            db: SQLAlchemy database session
            evaluation_request: The evaluation data to create
            background_tasks: FastAPI BackgroundTasks for async processing
            db_url: Database URL for background task session
        Returns:
            APIResponse containing the created evaluation with status 'pending',
            or error information if validation fails.
        """
        try:
            # 1. Validate rubric exists
            rubric = db.query(Rubric).filter(Rubric.id == evaluation_request.rubric_id).first()
            if rubric is None:
                logger.warning(
                    Messages.Rubric.NOT_FOUND_DETAIL.format(id=evaluation_request.rubric_id)
                )
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[Messages.Rubric.NOT_FOUND_DETAIL.format(id=evaluation_request.rubric_id)],
                    message=Messages.Rubric.NOT_FOUND,
                )

            # 2. Process briefing PDF
            try:
                briefing_processor = BriefingProcessor(evaluation_request.briefing_path)
                briefing_chunks = briefing_processor.process()
                # Serialize Document objects to dicts for database storage
                briefing_snapshot = json.dumps([
                    {"page_content": doc.page_content, "metadata": doc.metadata}
                    for doc in briefing_chunks
                ])
                logger.debug(f"Processed briefing into {len(briefing_chunks)} chunks")
            except FileNotFoundError:
                logger.warning(f"Briefing file not found: {evaluation_request.briefing_path}")
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[f"Briefing file not found: {evaluation_request.briefing_path}"],
                    message="Failed to process briefing",
                )
            except Exception as e:
                logger.error(f"Failed to process briefing: {e}")
                # Only try to remove the file if it exists
                if os.path.exists(evaluation_request.briefing_path):
                    os.remove(evaluation_request.briefing_path)
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[f"Failed to process briefing: {str(e)}"],
                    message="Failed to process briefing",
                )

            # 3. Create evaluation record with status 'pending'
            evaluation = Evaluation(
                rubric_id=evaluation_request.rubric_id,
                repo_url=evaluation_request.repo_url,
                briefing_snapshot=briefing_snapshot,
                status=settings.EVALUATION_STATUS_PENDING,
            )

            db.add(evaluation)
            db.commit()
            db.refresh(evaluation)

            evaluation_response = EvaluationResponse.model_validate(evaluation)

            logger.debug(f"Created evaluation {evaluation.id} with status '{settings.EVALUATION_STATUS_PENDING}'")

            # 4. Queue background task for AI processing
            background_tasks.add_task(
                run_evaluation_task,
                evaluation_id=evaluation.id,
                db_url=db_url,
                ai_provider=evaluation_request.ai_provider,
                ai_model=evaluation_request.ai_model,
                ai_api_key=evaluation_request.ai_api_key,
            )

            # Only try to remove the file if it exists
            if os.path.exists(evaluation_request.briefing_path):
                os.remove(evaluation_request.briefing_path)
            return APIResponse(
                success=True,
                data=evaluation_response,
                errors=None,
                message=Messages.Evaluation.CREATED,
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create evaluation: {e}")
            # Only try to remove the file if it exists
            if os.path.exists(evaluation_request.briefing_path):
                os.remove(evaluation_request.briefing_path)
            return APIResponse(
                success=False,
                data=None,
                errors=[str(e)],
                message=Messages.Evaluation.CREATE_FAILED,
            )

    def get_by_id(
        self, db: Session, evaluation_id: int
    ) -> APIResponse[EvaluationResponseWithFindings]:
        """
        Retrieve a single evaluation by ID with its findings.

        Args:
            db: SQLAlchemy database session
            evaluation_id: The ID of the evaluation to retrieve

        Returns:
            APIResponse containing the evaluation with nested findings,
            or error information if not found.
        """
        try:
            evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()

            if evaluation is None:
                logger.warning(Messages.Evaluation.NOT_FOUND_DETAIL.format(id=evaluation_id))
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[Messages.Evaluation.NOT_FOUND_DETAIL.format(id=evaluation_id)],
                    message=Messages.Evaluation.NOT_FOUND,
                )

            evaluation_response = EvaluationResponseWithFindings.model_validate(evaluation)

            logger.debug(f"Retrieved evaluation {evaluation_id}")

            return APIResponse(
                success=True,
                data=evaluation_response,
                errors=None,
                message=Messages.Evaluation.RETRIEVED,
            )
        except Exception as e:
            logger.error(f"Failed to retrieve evaluation {evaluation_id}: {e}")
            return APIResponse(
                success=False,
                data=None,
                errors=[str(e)],
                message=Messages.Evaluation.RETRIEVE_FAILED,
            )

    def get_all(self, db: Session) -> APIResponse[List[EvaluationResponse]]:
        """
        Retrieve all evaluations from the database.

        Args:
            db: SQLAlchemy database session

        Returns:
            APIResponse containing a list of evaluations on success,
            or error information on failure.
        """
        try:
            evaluations = db.query(Evaluation).all()

            evaluation_responses = [
                EvaluationResponse.model_validate(evaluation) for evaluation in evaluations
            ]

            logger.debug(f"Retrieved {len(evaluation_responses)} evaluations")

            return APIResponse(
                success=True,
                data=evaluation_responses,
                errors=None,
                message=Messages.Evaluation.LIST_RETRIEVED,
            )
        except Exception as e:
            logger.error(f"Failed to retrieve evaluations: {e}")
            return APIResponse(
                success=False,
                data=None,
                errors=[str(e)],
                message=Messages.Evaluation.LIST_RETRIEVE_FAILED,
            )

    def update(
        self, db: Session, evaluation_id: int, evaluation_request
    ) -> APIResponse[EvaluationResponse]:
        """
        Update an existing evaluation.

        Args:
            db: SQLAlchemy database session
            evaluation_id: The ID of the evaluation to update
            evaluation_request: The update data for the evaluation

        Returns:
            APIResponse containing the updated evaluation on success,
            or error information if not found or update fails.
        """
        try:
            evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()

            if evaluation is None:
                logger.warning(Messages.Evaluation.NOT_FOUND_DETAIL.format(id=evaluation_id))
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[Messages.Evaluation.NOT_FOUND_DETAIL.format(id=evaluation_id)],
                    message=Messages.Evaluation.NOT_FOUND,
                )

            # Update fields if provided
            if evaluation_request.status is not None:
                evaluation.status = evaluation_request.status
            if evaluation_request.total_score is not None:
                evaluation.total_score = evaluation_request.total_score
            if evaluation_request.ai_summary is not None:
                evaluation.ai_summary = evaluation_request.ai_summary

            db.commit()
            db.refresh(evaluation)

            evaluation_response = EvaluationResponse.model_validate(evaluation)

            logger.debug(f"Updated evaluation {evaluation_id}")

            return APIResponse(
                success=True,
                data=evaluation_response,
                errors=None,
                message=Messages.Evaluation.UPDATED,
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update evaluation {evaluation_id}: {e}")
            return APIResponse(
                success=False,
                data=None,
                errors=[str(e)],
                message=Messages.Evaluation.UPDATE_FAILED,
            )

    def delete(self, db: Session, evaluation_id: int) -> APIResponse[None]:
        """
        Delete an evaluation by ID.

        Args:
            db: SQLAlchemy database session
            evaluation_id: The ID of the evaluation to delete

        Returns:
            APIResponse indicating success or failure.
        """
        try:
            evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()

            if evaluation is None:
                logger.warning(Messages.Evaluation.NOT_FOUND_DETAIL.format(id=evaluation_id))
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[Messages.Evaluation.NOT_FOUND_DETAIL.format(id=evaluation_id)],
                    message=Messages.Evaluation.NOT_FOUND,
                )

            db.delete(evaluation)
            db.commit()

            logger.debug(f"Deleted evaluation {evaluation_id}")

            return APIResponse(
                success=True,
                data=None,
                errors=None,
                message=Messages.Evaluation.DELETED,
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete evaluation {evaluation_id}: {e}")
            return APIResponse(
                success=False,
                data=None,
                errors=[str(e)],
                message=Messages.Evaluation.DELETE_FAILED,
            )

    def get_finding_by_id(
        self, db: Session, evaluation_id: int, finding_id: int
    ) -> APIResponse[FindingResponse]:
        """
        Retrieve a single finding by ID.

        Args:
            db: SQLAlchemy database session
            evaluation_id: The ID of the parent evaluation
            finding_id: The ID of the finding to retrieve

        Returns:
            APIResponse containing the finding on success,
            or error information if not found.
        """
        try:
            from models import Finding
            
            finding = db.query(Finding).filter(
                Finding.id == finding_id,
                Finding.evaluation_id == evaluation_id
            ).first()

            if finding is None:
                logger.warning(Messages.Finding.NOT_FOUND_DETAIL.format(id=finding_id))
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[Messages.Finding.NOT_FOUND_DETAIL.format(id=finding_id)],
                    message=Messages.Finding.NOT_FOUND,
                )

            finding_response = FindingResponse.model_validate(finding)

            logger.debug(f"Retrieved finding {finding_id}")

            return APIResponse(
                success=True,
                data=finding_response,
                errors=None,
                message=Messages.Finding.RETRIEVED,
            )
        except Exception as e:
            logger.error(f"Failed to retrieve finding {finding_id}: {e}")
            return APIResponse(
                success=False,
                data=None,
                errors=[str(e)],
                message=Messages.Finding.RETRIEVE_FAILED,
            )

    def create_finding(
        self, db: Session, evaluation_id: int, finding_request
    ) -> APIResponse[FindingResponse]:
        """
        Create a new finding for an evaluation.

        Args:
            db: SQLAlchemy database session
            evaluation_id: The ID of the parent evaluation
            finding_request: The finding data to create

        Returns:
            APIResponse containing the created finding on success,
            or error information if evaluation not found or creation fails.
        """
        try:
            from models import Finding, Evaluation
            
            # Verify evaluation exists
            evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()
            if evaluation is None:
                logger.warning(Messages.Evaluation.NOT_FOUND_DETAIL.format(id=evaluation_id))
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[Messages.Evaluation.NOT_FOUND_DETAIL.format(id=evaluation_id)],
                    message=Messages.Evaluation.NOT_FOUND,
                )

            finding = Finding(
                evaluation_id=evaluation_id,
                criterion_id=finding_request.criterion_id,
                selected_level_id=finding_request.selected_level_id,
                file_path=finding_request.file_path,
                evidence_snippet=finding_request.evidence_snippet,
                improvement_suggestion=finding_request.improvement_suggestion,
            )

            db.add(finding)
            db.commit()
            db.refresh(finding)

            finding_response = FindingResponse.model_validate(finding)

            logger.debug(f"Created finding {finding.id} for evaluation {evaluation_id}")

            return APIResponse(
                success=True,
                data=finding_response,
                errors=None,
                message=Messages.Finding.CREATED,
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create finding for evaluation {evaluation_id}: {e}")
            return APIResponse(
                success=False,
                data=None,
                errors=[str(e)],
                message=Messages.Finding.CREATE_FAILED,
            )

    def update_finding(
        self, db: Session, evaluation_id: int, finding_id: int, finding_request
    ) -> APIResponse[FindingResponse]:
        """
        Update an existing finding.

        Args:
            db: SQLAlchemy database session
            evaluation_id: The ID of the parent evaluation
            finding_id: The ID of the finding to update
            finding_request: The update data for the finding

        Returns:
            APIResponse containing the updated finding on success,
            or error information if not found or update fails.
        """
        try:
            from models import Finding
            
            finding = db.query(Finding).filter(
                Finding.id == finding_id,
                Finding.evaluation_id == evaluation_id
            ).first()

            if finding is None:
                logger.warning(Messages.Finding.NOT_FOUND_DETAIL.format(id=finding_id))
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[Messages.Finding.NOT_FOUND_DETAIL.format(id=finding_id)],
                    message=Messages.Finding.NOT_FOUND,
                )

            # Update fields if provided
            if finding_request.selected_level_id is not None:
                finding.selected_level_id = finding_request.selected_level_id
            if finding_request.file_path is not None:
                finding.file_path = finding_request.file_path
            if finding_request.evidence_snippet is not None:
                finding.evidence_snippet = finding_request.evidence_snippet
            if finding_request.improvement_suggestion is not None:
                finding.improvement_suggestion = finding_request.improvement_suggestion

            db.commit()
            db.refresh(finding)

            finding_response = FindingResponse.model_validate(finding)

            logger.debug(f"Updated finding {finding_id}")

            return APIResponse(
                success=True,
                data=finding_response,
                errors=None,
                message=Messages.Finding.UPDATED,
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update finding {finding_id}: {e}")
            return APIResponse(
                success=False,
                data=None,
                errors=[str(e)],
                message=Messages.Finding.UPDATE_FAILED,
            )

    def delete_finding(
        self, db: Session, evaluation_id: int, finding_id: int
    ) -> APIResponse[None]:
        """
        Delete a finding by ID.

        Args:
            db: SQLAlchemy database session
            evaluation_id: The ID of the parent evaluation
            finding_id: The ID of the finding to delete

        Returns:
            APIResponse indicating success or failure.
        """
        try:
            from models import Finding
            
            finding = db.query(Finding).filter(
                Finding.id == finding_id,
                Finding.evaluation_id == evaluation_id
            ).first()

            if finding is None:
                logger.warning(Messages.Finding.NOT_FOUND_DETAIL.format(id=finding_id))
                return APIResponse(
                    success=False,
                    data=None,
                    errors=[Messages.Finding.NOT_FOUND_DETAIL.format(id=finding_id)],
                    message=Messages.Finding.NOT_FOUND,
                )

            db.delete(finding)
            db.commit()

            logger.debug(f"Deleted finding {finding_id}")

            return APIResponse(
                success=True,
                data=None,
                errors=None,
                message=Messages.Finding.DELETED,
            )
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete finding {finding_id}: {e}")
            return APIResponse(
                success=False,
                data=None,
                errors=[str(e)],
                message=Messages.Finding.DELETE_FAILED,
            )


# =============================================================================
# BACKGROUND TASK
# =============================================================================


def run_evaluation_task(
    evaluation_id: int, 
    db_url: str,
    ai_provider: str = None,
    ai_model: str = None,
    ai_api_key: str = None,
):
    """
    Background task for running the AI evaluation process.

    This task is triggered after the evaluation record is created and
    performs the long-running AI analysis. It manages the evaluation
    lifecycle: pending → processing → completed/failed.

    Args:
        evaluation_id: The ID of the evaluation to process
        db_url: Database URL for creating a new session
        ai_provider: AI provider to use (openai, gemini, groq) - optional
        ai_model: Specific model for the provider - optional
        ai_api_key: API key for the provider - optional
    """
    # Create a new database session for the background task
    # In test environments, this will use the mocked SessionLocal
    db = SessionLocal()

    try:
        logger.debug(f"Starting background evaluation task for evaluation {evaluation_id}")

        # 1. Update status to 'processing'
        evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()
        if evaluation is None:
            logger.error(f"Evaluation {evaluation_id} not found in background task")
            return

        evaluation.status = settings.EVALUATION_STATUS_PROCESSING
        db.commit()
        logger.debug(f"Evaluation {evaluation_id} status updated to '{settings.EVALUATION_STATUS_PROCESSING}'")
        
        
        # 1. Resolve provider/model/key based on request payload and server mode
        if ai_provider is None:
            ai_provider = AIProvider.GEMINI
        if ai_model is None:
            ai_model = get_model(ai_provider)

        # For Gemini server-default with Vertex enabled, no API key is required.
        uses_vertex_default_gemini = (
            ai_provider == AIProvider.GEMINI
            and ai_api_key is None
            and settings.VERTEX_ENABLED
        )

        if ai_api_key is None and not uses_vertex_default_gemini:
            ai_api_key = get_api_key(ai_provider)
        
        # 2. Resolve embedding configuration based on business logic
        if ai_provider == AIProvider.GROQ:
            resolved_emb_provider = AIProvider.GEMINI
            if settings.VERTEX_ENABLED:
                resolved_emb_model = settings.GEMINI_EMBEDDING_MODEL_VERTEX
                resolved_emb_key = None
            else:
                resolved_emb_model = settings.GEMINI_EMBEDDING_MODEL
                resolved_emb_key = settings.GEMINI_API_KEY
            logger.debug("Hybrid mode: Chat with GROQ and search with GEMINI")
        else:
            # For OpenAI and Gemini, use the same provider for embeddings
            resolved_emb_provider = ai_provider
            if ai_provider == AIProvider.OPENAI:
                resolved_emb_model = settings.OPENAI_EMBEDDING_MODEL
                resolved_emb_key = ai_api_key
            else:
                if settings.VERTEX_ENABLED and ai_api_key is None:
                    resolved_emb_model = settings.GEMINI_EMBEDDING_MODEL_VERTEX
                    resolved_emb_key = None
                else:
                    resolved_emb_model = settings.GEMINI_EMBEDDING_MODEL
                    resolved_emb_key = ai_api_key
            
        # 3. Initialize AI evaluation engine
        ai_engine = AIEvaluationEngine(
            provider=ai_provider, 
            model=ai_model, 
            api_key=ai_api_key,
            embedding_provider=resolved_emb_provider,
            embedding_model=resolved_emb_model,
            embedding_api_key=resolved_emb_key,
        )

        # 3. Parse briefing chunks from snapshot
        try:
            briefing_chunks = json.loads(evaluation.briefing_snapshot)
            logger.debug(f"Parsed {len(briefing_chunks)} briefing chunks")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse briefing snapshot for evaluation {evaluation_id}: {e}")
            raise RuntimeError(f"Invalid briefing data: {str(e)}")

        # 4. Run AI evaluation
        try:
            evaluation_result = ai_engine.evaluate_repository(
                evaluation_id=evaluation_id,
                repo_url=evaluation.repo_url,
                rubric_id=evaluation.rubric_id,
                briefing_chunks=briefing_chunks
            )
            
            logger.debug(f"AI evaluation completed for evaluation {evaluation_id}")
            
        except Exception as e:
            logger.error(f"AI evaluation failed for evaluation {evaluation_id}: {e}")
            # Re-raise to trigger error handling below
            raise

        # 5. Create finding records
        from models import Finding
        for finding_data in evaluation_result['findings']:
            finding = Finding(
                evaluation_id=evaluation_id,
                criterion_id=finding_data['criterion_id'],
                selected_level_id=finding_data['selected_level_id'],
                file_path=finding_data.get('file_path'),
                evidence_snippet=finding_data.get('evidence_snippet'),
                improvement_suggestion=finding_data.get('improvement_suggestion')
            )
            db.add(finding)

        # 6. Update evaluation with results
        evaluation.total_score = evaluation_result['total_score']
        evaluation.ai_summary = evaluation_result['ai_summary']
        evaluation.status = settings.EVALUATION_STATUS_COMPLETED
        
        db.commit()

        logger.debug(f"Evaluation {evaluation_id} completed successfully with score {evaluation_result['total_score']:.2f}")

    except Exception as e:
        # 4. On failure, update status to 'failed'
        logger.error(f"Evaluation {evaluation_id} failed: {e}")

        try:
            evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()
            if evaluation:
                evaluation.status = settings.EVALUATION_STATUS_FAILED
                evaluation.ai_summary = Messages.Evaluation.AI_SUMMARY_FAILED.format(error=str(e))
                db.commit()
        except Exception as commit_error:
            logger.error(f"Failed to update evaluation status to '{settings.EVALUATION_STATUS_FAILED}': {commit_error}")

    finally:
        db.close()