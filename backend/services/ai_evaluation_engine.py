"""
AI Evaluation Engine - Core service for running repository evaluations.

This module orchestrates the complete AI evaluation workflow:
1. Repository cloning and code analysis
2. RAG-augmented criterion evaluation
3. Finding creation with WHIS data
4. Score calculation and aggregation
5. AI summary generation
"""

import json
import time
from typing import List, Dict, Any, Optional

from core.logging_config import logger
from core.settings import settings, get_api_key, get_model, AIProvider
from core.database import SessionLocal
from core.messages import Messages
from models import Rubric, Criterion, Level
from services.git_loader import GitLoaderService
from services.ai_client import AIClient
from services.context_engine import ContextEngine
from services.prompts import build_grading_prompt, build_summary_prompt


class AIEvaluationEngine:
    """
    Core AI evaluation engine that orchestrates the complete evaluation workflow.
    
    This service handles:
    - Repository cloning and code analysis
    - RAG-augmented criterion evaluation using different AI providers
    - Finding creation with WHIS data (Where, How, Improvement, Score)
    - Weighted score calculation
    - AI summary generation
    """
    
    embedding_provider = None
    embedding_model = None
    embedding_api_key = None
    SUMMARY_MAX_RETRIES = 3
    SUMMARY_RETRY_BASE_SECONDS = 2
    OUT_OF_SCOPE_HINTS = (
        "fuera del alcance",
        "out of scope",
        "no aplica",
        "no aplica al proyecto",
        "not mentioned in the briefing",
    )

    def __init__(
        self,
        provider: AIProvider = AIProvider.GEMINI,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        embedding_provider: Optional[str] = None,
        embedding_model: Optional[str] = None,
        embedding_api_key: Optional[str] = None,
    ):
        """Initialize the AI evaluation engine with required services."""
        self.git_loader = GitLoaderService()
        
        # If no model provided, use setings from provider
        if model is None:
            model = get_model(provider)
        
        # If no API key provided, use settings based on provider except
        # Gemini server-default mode with Vertex enabled (ADC path, no API key).
        provider_value = getattr(provider, "value", provider)
        if isinstance(provider_value, str):
            provider_value = provider_value.lower().strip()

        uses_vertex_default_gemini = (
            provider_value == "gemini"
            and api_key is None
            and settings.VERTEX_ENABLED
        )

        if api_key is None and not uses_vertex_default_gemini:
            api_key = get_api_key(provider)
            
        self.embedding_provider = embedding_provider
        self.embedding_model = embedding_model
        self.embedding_api_key = embedding_api_key
        
        logger.debug(f"Provider: {provider}, Model: {model}, API Key: {api_key[:5] if api_key else 'None'}")
        logger.debug(f"Embedding Provider: {self.embedding_provider}, Model: {self.embedding_model}, API Key: {self.embedding_api_key[:5] if self.embedding_api_key else 'None'}")
        self.ai_client = AIClient(provider=provider, model=model, api_key=api_key)

    def evaluate_repository(
        self, 
        evaluation_id: int, 
        repo_url: str, 
        rubric_id: int, 
        briefing_chunks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Execute the complete AI evaluation workflow.
        
        Args:
            evaluation_id: ID of the evaluation record
            repo_url: URL of the repository to evaluate
            rubric_id: ID of the rubric to use for evaluation
            briefing_chunks: List of briefing document chunks for RAG context
            
        Returns:
            Dictionary containing evaluation results with findings, total score, and AI summary
        """
        logger.debug(f"Starting AI evaluation for evaluation {evaluation_id}")
        
        # 1. Clone repository and process code
        try:
            logger.debug(f"Cloning repository: {repo_url}")
            code_chunks = self.git_loader.fetch_and_process(repo_url)
            logger.debug(f"Repository cloned successfully: {len(code_chunks)} code chunks generated")
        except Exception as e:
            logger.error(f"Failed to clone repository {repo_url}: {e}")
            raise RuntimeError(Messages.AIRepository.CLONING_FAILED.format(
                repo_url=repo_url, 
                error=str(e)
            )) from e

        # 2. Load rubric criteria and levels
        try:
            rubric_data = self._load_rubric_data(rubric_id)
            logger.debug(f"Loaded rubric {rubric_id} with {len(rubric_data['criteria'])} criteria")
        except Exception as e:
            logger.error(f"Failed to load rubric {rubric_id}: {e}")
            raise RuntimeError(Messages.AIRubric.LOADING_FAILED.format(
                rubric_id=rubric_id, 
                error=str(e)
            )) from e

        # 3. Build ContextEngine ONCE for all criteria (avoids re-vectorizing per criterion)
        try:
            all_documents = list(briefing_chunks) + list(code_chunks)
            context_engine = ContextEngine(
                all_documents,
                embedding_provider=self.embedding_provider,
                embedding_model=self.embedding_model,
                embedding_api_key=self.embedding_api_key,
            )
            logger.debug(f"ContextEngine built with {len(all_documents)} documents")
        except Exception as e:
            logger.error(f"Failed to build ContextEngine: {e}")
            raise RuntimeError(f"Failed to build vector index: {str(e)}") from e

        # 4. Evaluate each criterion
        findings = []
        total_weighted_score = 0.0
        max_possible = rubric_data.get('max_possible_score', 0.0)
        
        for criterion in rubric_data['criteria']:
            try:
                logger.debug(f"Evaluating criterion: {criterion['title']}")
                
                # Evaluate this criterion
                finding_result = self._evaluate_criterion(
                    criterion=criterion,
                    context_engine=context_engine,
                )
                
                if finding_result:
                    finding_result['criterion_title'] = criterion['title']
                    findings.append(finding_result)
                    criterion_max = max([l['score_points'] for l in criterion['levels']]) if criterion['levels'] else 0.0

                    if finding_result.get('is_not_applicable'):
                        # N/A criteria do not penalize the student score.
                        max_possible -= criterion_max * criterion['weight']
                        logger.debug(f"Criterion '{criterion['title']}' marked as N/A (out of scope)")
                    else:
                        total_weighted_score += finding_result['score_points'] * criterion['weight']
                        logger.debug(f"Criterion '{criterion['title']}' evaluated: {finding_result['score_points']} points")
                else:
                    # Create a failed finding record when _evaluate_criterion returns None
                    findings.append({
                        'criterion_id': criterion['id'],
                        'criterion_title': criterion['title'],
                        'selected_level_id': None,
                        'file_path': None,
                        'evidence_snippet': None,
                        'improvement_suggestion': "Evaluation failed: No result returned",
                        'score_points': 0.0
                    })
                
            except Exception as e:
                logger.error(f"Failed to evaluate criterion '{criterion['title']}': {e}")
                # Create a failed finding record
                findings.append({
                    'criterion_id': criterion['id'],
                    'criterion_title': criterion['title'],
                    'selected_level_id': None,
                    'file_path': None,
                    'evidence_snippet': None,
                    'improvement_suggestion': Messages.AIEvaluation.CRITERION_EVALUATION_FAILED.format(
                        criterion_title=criterion['title'], 
                        error=str(e)
                    ),
                    'score_points': 0.0
                })

        # 5. Calculate total score and normalize to 100-point scale
        if max_possible > 0:
            total_score = (total_weighted_score / max_possible) * 100
        else:
            total_score = 0.0

        total_score = round(total_score, 1)
            
        logger.debug(f"Evaluation completed. Total score: {total_score:.2f}")

        # 6. Generate AI summary
        try:
            ai_summary = self._generate_ai_summary(
                repo_url=repo_url,
                rubric_title=rubric_data['title'],
                findings=findings,
                total_score=total_score
            )
            logger.debug("AI summary generated successfully")
        except Exception as e:
            logger.error(f"Failed to generate AI summary: {e}")
            ai_summary = Messages.AIEvaluation.AI_SUMMARY_GENERATION_FAILED.format(error=str(e))

        return {
            'findings': findings,
            'total_score': total_score,
            'ai_summary': ai_summary
        }

    def _load_rubric_data(self, rubric_id: int) -> Dict[str, Any]:
        """
        Load rubric data including criteria and levels from database.
        
        Args:
            rubric_id: ID of the rubric to load
            
        Returns:
            Dictionary containing rubric title and list of criteria with levels
        """
        db = SessionLocal()
        try:
            # Load rubric
            rubric = db.query(Rubric).filter(Rubric.id == rubric_id).first()
            if not rubric:
                raise ValueError(Messages.AIRubric.NOT_FOUND.format(rubric_id=rubric_id))

            # Load criteria with levels
            criteria = db.query(Criterion).filter(Criterion.rubric_id == rubric_id).all()
            
            criteria_data = []
            max_possible_score = 0.0
            for criterion in criteria:
                levels = db.query(Level).filter(Level.criterion_id == criterion.id).all()
                
                # Calculate max points for this criterion
                max_level_points = max([l.score_points for l in levels]) if levels else 0.0
                max_possible_score += max_level_points * criterion.weight

                criteria_data.append({
                    'id': criterion.id,
                    'title': criterion.title,
                    'description': criterion.description,
                    'weight': criterion.weight,
                    'levels': [
                        {
                            'id': level.id,
                            'title': level.level_title,
                            'description': level.level_description,
                            'score_points': level.score_points
                        }
                        for level in levels
                    ]
                })

            return {
                'id': rubric.id,
                'title': rubric.title,
                'description': rubric.description,
                'criteria': criteria_data,
                'max_possible_score': max_possible_score
            }

        finally:
            db.close()

    def _evaluate_criterion(
        self, 
        criterion: Dict[str, Any],
        context_engine: ContextEngine,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate a single criterion using RAG-augmented AI analysis.
        
        Args:
            criterion: Dictionary containing criterion data and levels
            context_engine: Pre-built ContextEngine with all documents indexed
            
        Returns:
            Dictionary containing finding data or None if evaluation failed
        """
        # Prepare RAG context
        rag_context = self._prepare_rag_context(criterion, context_engine)
        
        # Build prompt using centralized prompt templates (prompts.py)
        prompt = build_grading_prompt(
            criterion=criterion,
            levels=criterion['levels'],
            briefing_context=rag_context['briefing'],
            code_evidence=rag_context['code'],
        )
        
        try:
            # Call AI provider API
            response_text = self.ai_client.chat(prompt)
            
            # Parse response
            evaluation_result = self._parse_evaluation_response(
                response_text,
                criterion
            )
            
            return evaluation_result
            
        except Exception as e:
            logger.error(f"AI API call failed for criterion '{criterion['title']}': {e}")
            return None

    def _prepare_rag_context(
        self, 
        criterion: Dict[str, Any],
        context_engine: ContextEngine,
    ) -> Dict[str, str]:
        """
        Prepare RAG context using ContextEngine semantic search.

        Uses the pre-built FAISS index to retrieve the most relevant
        chunks for the given criterion via semantic similarity search.

        Args:
            criterion: The criterion being evaluated
            context_engine: Pre-built ContextEngine with all documents indexed
            
        Returns:
            Dictionary with 'briefing' and 'code' context strings
        """
        # Search semantically using the pre-built index
        query = f"{criterion['title']}: {criterion['description']}"
        relevant_chunks = context_engine.get_relevant_context(query, k=8)

        # Separate briefing and code results for structured context
        briefing_results = [c for c in relevant_chunks if c['metadata'].get('type') in ('requirement', 'documentation')]
        code_results = [c for c in relevant_chunks if c['metadata'].get('type') not in ('requirement', 'documentation')]

        # Limit context size to avoid exceeding model token limits
        max_chunks = settings.RAG_MAX_CHUNKS
        max_chars = settings.RAG_MAX_CHUNK_CHARS

        briefing_context = "\n\n".join([
            f"Requirement {i+1}: {c['page_content'][:max_chars]}"
            for i, c in enumerate(briefing_results[:max_chunks])
        ]) or "No relevant requirements found."

        code_context = "\n\n".join([
            f"File {i+1} ({c['metadata'].get('file_path', 'unknown')}): {c['page_content'][:max_chars]}"
            for i, c in enumerate(code_results[:max_chunks])
        ]) or "No relevant code found."

        return {
            'briefing': briefing_context,
            'code': code_context,
        }

    def _build_evaluation_prompt(self, criterion: Dict[str, Any], context: str) -> str:
        """
        Build the evaluation prompt for AI API.

        .. deprecated::
            This method is kept for backward compatibility.
            New code should call ``build_grading_prompt()`` from ``prompts.py`` directly.

        Args:
            criterion: The criterion being evaluated
            context: RAG context containing relevant code and requirements

        Returns:
            String containing the evaluation prompt
        """
        return build_grading_prompt(
            criterion=criterion,
            levels=criterion['levels'],
            briefing_context=context,
            code_evidence=context,
        )

    def _parse_evaluation_response(self, response_text: str, criterion: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse the AI response and extract evaluation data.
        
        Args:
            response_text: Raw response from AI API
            criterion: The criterion being evaluated
            
        Returns:
            Dictionary containing parsed evaluation result
        """
        try:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                response_data = json.loads(json_match.group())
            else:
                # Fallback if no JSON found
                response_data = {"level_id": criterion['levels'][0]['id'], "evidence": "No JSON response found", "improvement": "Unable to parse response"}
            
            evidence_text = str(response_data.get('evidence') or "")
            improvement_text = str(response_data.get('improvement') or "")
            out_of_scope = bool(response_data.get('out_of_scope')) or self._is_out_of_scope_response(
                evidence_text,
                improvement_text,
            )

            if out_of_scope:
                normalized_improvement = improvement_text.strip()
                if not normalized_improvement:
                    normalized_improvement = "N/A: criterio fuera del alcance del proyecto según el briefing."
                elif not normalized_improvement.lower().startswith("n/a"):
                    normalized_improvement = f"N/A: {normalized_improvement}"

                return {
                    'criterion_id': criterion['id'],
                    'selected_level_id': None,
                    'file_path': response_data.get('file_path'),
                    'evidence_snippet': evidence_text or "Criterio fuera del alcance definido en el briefing.",
                    'improvement_suggestion': normalized_improvement,
                    'score_points': 0.0,
                    'is_not_applicable': True,
                }

            # Find the selected level
            selected_level = None
            for level in criterion['levels']:
                if level['id'] == response_data.get('level_id'):
                    selected_level = level
                    break
            
            if not selected_level:
                selected_level = criterion['levels'][0]  # Default to lowest level
            
            return {
                'criterion_id': criterion['id'],
                'selected_level_id': selected_level['id'],
                'file_path': response_data.get('file_path'),
                'evidence_snippet': evidence_text,
                'improvement_suggestion': improvement_text,
                'score_points': selected_level['score_points'],
                'is_not_applicable': False,
            }
            
        except Exception as e:
            logger.error(f"Failed to parse evaluation response: {e}")
            # Return fallback result
            return {
                'criterion_id': criterion['id'],
                'selected_level_id': criterion['levels'][0]['id'],
                'file_path': None,
                'evidence_snippet': f"Parse error: {str(e)}",
                'improvement_suggestion': "Unable to parse AI response",
                'score_points': criterion['levels'][0]['score_points'],
                'is_not_applicable': False,
            }

    def _is_out_of_scope_response(self, evidence_text: str, improvement_text: str) -> bool:
        """Detect out-of-scope evaluations from model text when JSON flag is missing."""
        combined = f"{evidence_text} {improvement_text}".lower()
        return any(hint in combined for hint in self.OUT_OF_SCOPE_HINTS)

    def _generate_ai_summary(
        self, 
        repo_url: str, 
        rubric_title: str, 
        findings: List[Dict[str, Any]], 
        total_score: float
    ) -> str:
        """
        Generate a comprehensive AI summary of the evaluation.
        
        Args:
            repo_url: URL of the evaluated repository
            rubric_title: Title of the rubric used
            findings: List of all criterion findings
            total_score: Overall evaluation score
            
        Returns:
            String containing the AI-generated summary
        """
        # Map internal finding keys to the format expected by build_summary_prompt
        findings_for_prompt = [
            {
                'criterion_title': f.get('criterion_title') or f"Criterion {f.get('criterion_id', 'Unknown')}",
                'score_points': f.get('score_points', 0),
                'evidence': f.get('evidence_snippet') or 'N/A',
                'improvement': f.get('improvement_suggestion') or 'N/A',
            }
            for f in findings
        ]

        prompt = build_summary_prompt(
            repo_url=repo_url,
            rubric_title=rubric_title,
            findings_summary=findings_for_prompt,
            total_score=total_score,
        )

        last_error = None
        for attempt in range(1, self.SUMMARY_MAX_RETRIES + 1):
            try:
                response_text = self.ai_client.chat(prompt)
                return response_text
            except Exception as e:
                last_error = e
                error_text = str(e)
                is_quota_error = (
                    "RESOURCE_EXHAUSTED" in error_text
                    or "429" in error_text
                )

                if is_quota_error and attempt < self.SUMMARY_MAX_RETRIES:
                    wait_seconds = self.SUMMARY_RETRY_BASE_SECONDS * attempt
                    logger.warning(
                        "Summary generation hit quota (attempt %s/%s). Retrying in %ss",
                        attempt,
                        self.SUMMARY_MAX_RETRIES,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)
                    continue

                logger.error(f"Failed to generate AI summary: {e}")
                break

        return self._build_fallback_summary(
            repo_url=repo_url,
            rubric_title=rubric_title,
            findings=findings_for_prompt,
            total_score=total_score,
            error=last_error,
        )

    def _build_fallback_summary(
        self,
        repo_url: str,
        rubric_title: str,
        findings: List[Dict[str, Any]],
        total_score: float,
        error: Exception | None,
    ) -> str:
        """Build a deterministic summary when AI summary generation is unavailable."""
        total_findings = len(findings)
        if total_findings == 0:
            return (
                f"Resumen automático no disponible temporalmente ({error}). "
                "No se encontraron hallazgos para resumir."
            )

        sorted_findings = sorted(
            findings,
            key=lambda f: f.get("score_points", 0),
            reverse=True,
        )

        top_items = sorted_findings[:3]
        low_items = sorted_findings[-3:]

        top_text = ", ".join(
            [f"{f.get('criterion_title', 'Criterio')} ({f.get('score_points', 0)} pts)" for f in top_items]
        )
        low_text = ", ".join(
            [f"{f.get('criterion_title', 'Criterio')} ({f.get('score_points', 0)} pts)" for f in low_items]
        )

        summary_lines = [
            "Resumen generado en modo fallback por límite temporal de cuota del proveedor IA.",
            f"Repositorio evaluado: {repo_url}",
            f"Rúbrica: {rubric_title}",
            f"Puntaje total: {total_score:.2f}/100",
            f"Criterios evaluados: {total_findings}",
            f"Fortalezas destacadas: {top_text}",
            f"Áreas prioritarias de mejora: {low_text}",
            "Sugerencia: reintentar en unos minutos para obtener un resumen narrativo completo del modelo.",
        ]

        if error is not None:
            summary_lines.insert(1, f"Motivo técnico: {error}")

        return "\n".join(summary_lines)
