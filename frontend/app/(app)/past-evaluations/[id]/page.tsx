'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import {
  ArrowLeft,
  FileText,
  Calendar,
  ExternalLink,
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  FileCode,
  Lightbulb,
  BookOpen,
  AlertTriangle,
} from 'lucide-react';
import { MarkdownRenderer } from '@/components/ui/MarkdownRenderer';

// ---------------------------------------------------------------------------
// Types — aligned with backend schemas/evaluation.py + schemas/rubric.py
// ---------------------------------------------------------------------------

interface FindingResponse {
  id: number;
  criterion_id: number;
  selected_level_id: number | null;
  file_path: string | null;
  evidence_snippet: string | null;
  improvement_suggestion: string | null;
}

interface EvaluationDetail {
  id: number;
  rubric_id: number;
  repo_url: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  total_score: number | null;
  ai_summary: string | null;
  created_at: string;
  findings: FindingResponse[];
}

interface RubricLevel {
  id: number;
  level_title: string;
  level_description: string;
  score_points: number;
}

interface RubricCriterion {
  id: number;
  title: string;
  description: string;
  weight: number;
  levels: RubricLevel[];
}

interface RubricDetail {
  id: number;
  title: string;
  description: string;
  created_at: string;
  criteria: RubricCriterion[];
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  errors: string[] | null;
  message: string;
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

/** Extracts "owner/repo" from a GitHub URL, falls back to the raw URL. */
function shortRepo(url: string): string {
  try {
    const { pathname } = new URL(url);
    return pathname.replace(/^\//, '').replace(/\.git$/, '');
  } catch {
    return url;
  }
}

/** Formats an ISO date string as "Mon D, YYYY HH:MM". */
function formatDatetime(iso: string): string {
  return new Date(iso).toLocaleString('es-ES', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** Tailwind classes for the total-score badge. */
function scoreBadgeClass(score: number | null): string {
  if (score === null) return 'bg-gray-100 text-gray-500';
  if (score >= 85) return 'bg-green-100 text-green-700';
  if (score >= 70) return 'bg-yellow-100 text-yellow-700';
  return 'bg-red-100 text-red-700';
}

function formatScore(score: number | null): string {
  if (score === null) return '—';
  return score.toLocaleString('es-ES', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

/** Tailwind classes for the status pill. */
function statusPillClass(status: EvaluationDetail['status']): string {
  switch (status) {
    case 'completed':  return 'bg-green-100 text-green-700';
    case 'processing': return 'bg-blue-100 text-blue-700';
    case 'pending':    return 'bg-yellow-100 text-yellow-700';
    case 'failed':     return 'bg-red-100 text-red-700';
    default:           return 'bg-gray-100 text-gray-500';
  }
}

/** Maps status values to Spanish display labels. */
function translateStatus(status: EvaluationDetail['status']): string {
  const map: Record<string, string> = {
    pending:    'Pendiente',
    processing: 'Procesando',
    completed:  'Completado',
    failed:     'Fallido',
  };
  return map[status] ?? status;
}

/** Status icon component for the evaluation state. */
function StatusIcon({ status }: { status: EvaluationDetail['status'] }) {
  switch (status) {
    case 'completed':  return <CheckCircle className="w-4 h-4 text-green-600" />;
    case 'processing': return <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />;
    case 'pending':    return <Clock className="w-4 h-4 text-yellow-600" />;
    case 'failed':     return <XCircle className="w-4 h-4 text-red-600" />;
    default:           return null;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function EvaluationDetailPage() {
  const params  = useParams();
  const evalId  = Number(params.id);

  // -- Data state -----------------------------------------------------------
  const [evaluation, setEvaluation] = useState<EvaluationDetail | null>(null);
  const [rubric,     setRubric]     = useState<RubricDetail | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);

  // -- Lookup maps (derived synchronously when rubric changes) ---------------
  const criterionMap = React.useMemo<Record<number, RubricCriterion>>(
    () => Object.fromEntries((rubric?.criteria ?? []).map((c) => [c.id, c])),
    [rubric],
  );

  const levelMap = React.useMemo<Record<number, RubricLevel>>(() => {
    const entries: [number, RubricLevel][] = [];
    (rubric?.criteria ?? []).forEach((c) =>
      c.levels.forEach((l) => entries.push([l.id, l])),
    );
    return Object.fromEntries(entries);
  }, [rubric]);

  // -- Fetch evaluation, then rubric ----------------------------------------
  useEffect(() => {
    if (!evalId || isNaN(evalId)) {
      setError('ID de evaluación no válido.');
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);

      try {
        // Step 1: fetch evaluation detail
        const evalRes = await fetch(`/api/v1/evaluations/${evalId}`);
        if (!evalRes.ok) {
          throw new Error(
            evalRes.status === 404
              ? 'Evaluación no encontrada.'
              : `Failed to load evaluation (${evalRes.status})`,
          );
        }
        const evalJson: ApiResponse<EvaluationDetail> = await evalRes.json();
        if (!evalJson.success) throw new Error(evalJson.message || 'Failed to load evaluation');
        if (cancelled) return;

        const ev = evalJson.data;
        setEvaluation(ev);

        // Step 2: fetch rubric detail for name resolution
        const rubricRes = await fetch(`/api/v1/rubrics/${ev.rubric_id}`);
        if (rubricRes.ok) {
          const rubricJson: ApiResponse<RubricDetail> = await rubricRes.json();
          if (!cancelled && rubricJson.success) setRubric(rubricJson.data);
        }
        // Silently continue if rubric fetch fails — finding IDs will fall back
        // to displaying numeric IDs rather than names.
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Unexpected error');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [evalId]);

  // -- Poll for status changes while evaluation is in-flight ----------------
  // Activates only when status is pending/processing; stops when settled.
  const POLL_INTERVAL_MS = 5_000;

  useEffect(() => {
    const isActive =
      evaluation?.status === 'pending' || evaluation?.status === 'processing';
    if (!isActive || loading) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/v1/evaluations/${evalId}`);
        if (!res.ok) return;
        const json: ApiResponse<EvaluationDetail> = await res.json();
        if (!json.success) return;

        const updated = json.data;
        setEvaluation(updated);

        // When the evaluation just completed, fetch the rubric so criterion
        // and level names resolve correctly in the findings section.
        if (updated.status === 'completed' && !rubric) {
          const rubricRes = await fetch(`/api/v1/rubrics/${updated.rubric_id}`);
          if (rubricRes.ok) {
            const rubricJson: ApiResponse<RubricDetail> = await rubricRes.json();
            if (rubricJson.success) setRubric(rubricJson.data);
          }
        }
      } catch {
        // Silently ignore polling errors — non-critical background update.
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  // Re-evaluate on every status change or when loading flips.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [evaluation?.status, evalId, loading]);

  // -- Loading skeleton ------------------------------------------------------
  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6">
        {/* Back link skeleton */}
        <div className="h-4 w-32 bg-gray-200 rounded animate-pulse" />
        {/* Header skeleton */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4 animate-pulse">
          <div className="h-6 w-64 bg-gray-200 rounded" />
          <div className="flex gap-4">
            <div className="h-4 w-32 bg-gray-100 rounded" />
            <div className="h-4 w-24 bg-gray-100 rounded" />
          </div>
        </div>
        {/* Content skeleton */}
        {[...Array(3)].map((_, i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-200 p-6 space-y-3 animate-pulse">
            <div className="h-5 w-40 bg-gray-200 rounded" />
            <div className="h-3 w-full bg-gray-100 rounded" />
            <div className="h-3 w-3/4 bg-gray-100 rounded" />
          </div>
        ))}
      </div>
    );
  }

  // -- Error state -----------------------------------------------------------
  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        <Link
          href="/past-evaluations"
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Volver a las evaluaciones
        </Link>
        <div className="rounded-xl bg-red-50 border border-red-200 px-6 py-10 text-center">
          <XCircle className="w-10 h-10 text-red-400 mx-auto mb-3" />
          <p className="text-base font-semibold text-red-700">{error}</p>
          <Link
            href="/past-evaluations"
            className="mt-4 inline-flex items-center gap-1.5 text-sm text-red-600 hover:underline"
          >
            Volver a Evaluaciones Pasadas
          </Link>
        </div>
      </div>
    );
  }

  if (!evaluation) return null;

  const isCompleted   = evaluation.status === 'completed';
  const isInProgress  = evaluation.status === 'pending' || evaluation.status === 'processing';
  const isFailed      = evaluation.status === 'failed';

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-6">

      {/* Back link */}
      <Link
        href="/past-evaluations"
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Volver a las evaluaciones
      </Link>

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 sm:p-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="min-w-0 flex-1">
            {/* Repository */}
            <div className="flex items-center gap-2 flex-wrap">
              <FileText className="w-5 h-5 text-indigo-600 shrink-0" />
              <h1 className="text-xl font-bold text-gray-900 truncate">
                {shortRepo(evaluation.repo_url)}
              </h1>
              <a
                href={evaluation.repo_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-gray-400 hover:text-indigo-600 transition-colors shrink-0"
                title="Abrir repositorio"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            </div>

            {/* Meta row */}
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-500">
              {/* Rubric */}
              {rubric && (
                <span className="flex items-center gap-1">
                  <BookOpen className="w-3.5 h-3.5 shrink-0" />
                  {rubric.title}
                </span>
              )}
              {/* Date */}
              <span className="flex items-center gap-1">
                <Calendar className="w-3.5 h-3.5 shrink-0" />
                {formatDatetime(evaluation.created_at)}
              </span>
            </div>
          </div>

          {/* Score + Status */}
          <div className="flex items-center gap-3 shrink-0">
            {/* Total score badge */}
            <div
              className={`flex items-center justify-center w-16 h-16 rounded-full text-xl font-bold shadow-sm ${scoreBadgeClass(evaluation.total_score)}`}
              title="Puntuación total"
            >
              {formatScore(evaluation.total_score)}
            </div>
            {/* Status pill */}
            <span
              className={`inline-flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-full ${statusPillClass(evaluation.status)}`}
            >
              <StatusIcon status={evaluation.status} />
              {translateStatus(evaluation.status)}
            </span>
          </div>
        </div>

        {/* Evaluation ID */}
        <p className="mt-3 text-xs text-gray-400">Evaluation #{evaluation.id}</p>
      </div>

      {/* ── In-progress banner ───────────────────────────────────────────── */}
      {isInProgress && (
        <div className="rounded-xl bg-blue-50 border border-blue-200 px-4 sm:px-6 py-4 sm:py-5 flex items-start gap-3">
          <Loader2 className="w-5 h-5 text-blue-500 animate-spin shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-blue-800">
              Evaluación en progreso
            </p>
            <p className="text-sm text-blue-700 mt-0.5">
              La IA está analizando el repositorio. Los hallazgos aparecerán aquí automáticamente cuando la evaluación finalice.
            </p>
          </div>
        </div>
      )}

      {/* ── Failed banner ────────────────────────────────────────────────── */}
      {isFailed && (
        <div className="rounded-xl bg-red-50 border border-red-200 px-4 sm:px-6 py-4 sm:py-5 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-red-800">Evaluación fallida</p>
            {evaluation.ai_summary && (
              <MarkdownRenderer
                content={evaluation.ai_summary}
                className="mt-1 [&_p]:text-red-700 [&_li]:text-red-700 [&_blockquote]:text-red-700 [&_a]:text-red-800"
              />
            )}
          </div>
        </div>
      )}

      {/* ── AI Summary ───────────────────────────────────────────────────── */}
      {isCompleted && evaluation.ai_summary && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 sm:p-6">
          <h2 className="text-base font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Lightbulb className="w-4 h-4 text-yellow-500" />
            Resumen IA
          </h2>
          <MarkdownRenderer content={evaluation.ai_summary} />
        </div>
      )}

      {/* ── Findings ─────────────────────────────────────────────────────── */}
      {isCompleted && (
        <>
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900">
              Hallazgos
              <span className="ml-2 text-sm font-normal text-gray-400">
                ({evaluation.findings.length})
              </span>
            </h2>
          </div>

          {evaluation.findings.length === 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-4 sm:px-6 py-10 sm:py-12 text-center">
              <FileText className="w-10 h-10 text-gray-200 mx-auto mb-3" />
              <p className="text-sm font-medium text-gray-600">Sin hallazgos registrados</p>
              <p className="text-xs text-gray-400 mt-1">
                La evaluación se completó pero no generó hallazgos individuales.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {evaluation.findings.map((finding) => {
                const criterion = criterionMap[finding.criterion_id];
                const level     = finding.selected_level_id != null
                  ? levelMap[finding.selected_level_id]
                  : null;
                const isOutOfScope =
                  finding.selected_level_id === null &&
                  (
                    (finding.improvement_suggestion ?? '').toLowerCase().startsWith('n/a')
                    || (finding.evidence_snippet ?? '').toLowerCase().includes('fuera del alcance')
                  );

                return (
                  <div
                    key={finding.id}
                    className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden"
                  >
                    {/* Finding header */}
                    <div className="px-4 sm:px-6 py-4 bg-gray-50 border-b border-gray-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-gray-900">
                          {criterion?.title ?? `Criterion #${finding.criterion_id}`}
                        </p>
                        {criterion?.description && (
                          <p className="text-xs text-gray-500 mt-0.5 line-clamp-1">
                            {criterion.description}
                          </p>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 shrink-0">
                        {/* Weight badge */}
                        {criterion && (
                          <span className="text-xs text-indigo-600 bg-indigo-50 border border-indigo-100 rounded-full px-2.5 py-0.5">
                            peso: {criterion.weight}
                          </span>
                        )}
                        {/* Score badge */}
                        {level ? (
                          <span className="text-xs font-bold text-white bg-indigo-600 rounded-full px-2.5 py-1">
                            {level.score_points} pts — {level.level_title}
                          </span>
                        ) : isOutOfScope ? (
                          <span className="text-xs text-blue-700 bg-blue-50 border border-blue-100 rounded-full px-2.5 py-1">
                            N/A — Fuera de alcance
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400 bg-gray-100 rounded-full px-2.5 py-1">
                            Sin nivel asignado
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Finding body */}
                    <div className="px-4 sm:px-6 py-4 space-y-4">
                      {/* File path */}
                      {finding.file_path && (
                        <div className="flex items-start gap-2">
                          <FileCode className="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />
                          <code className="text-xs text-indigo-700 bg-indigo-50 rounded px-2 py-0.5 break-all">
                            {finding.file_path}
                          </code>
                        </div>
                      )}

                      {/* Evidence snippet */}
                      {finding.evidence_snippet && (
                        <div>
                          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1.5">
                            Evidencia
                          </p>
                          <div className="bg-gray-50 border border-gray-100 rounded-lg p-3 overflow-x-auto">
                            <MarkdownRenderer content={finding.evidence_snippet} />
                          </div>
                        </div>
                      )}

                      {/* Improvement suggestion */}
                      {finding.improvement_suggestion && (
                        <div className="flex items-start gap-2 rounded-lg bg-amber-50 border border-amber-100 px-4 py-3">
                          <Lightbulb className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-amber-800 mb-0.5">
                              Sugerencia de mejora
                            </p>
                            <MarkdownRenderer
                              content={finding.improvement_suggestion}
                              className="[&_p]:text-amber-700 [&_li]:text-amber-700 [&_blockquote]:text-amber-700 [&_a]:text-amber-800"
                            />
                          </div>
                        </div>
                      )}

                      {/* No content fallback */}
                      {!finding.file_path && !finding.evidence_snippet && !finding.improvement_suggestion && (
                        <p className="text-xs text-gray-400 italic">
                          No se registró información detallada para este hallazgo.
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
