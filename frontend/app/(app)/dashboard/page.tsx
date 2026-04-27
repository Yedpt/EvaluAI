'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  FileText,
  Award,
  BookOpen,
  TrendingUp,
  ArrowRight,
} from 'lucide-react';
import { PageHeader } from '@/components/layout';

// ---------------------------------------------------------------------------
// Types — mirror the API schemas exactly
// ---------------------------------------------------------------------------

interface EvaluationResponse {
  id: number;
  rubric_id: number;
  repo_url: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  total_score: number | null;
  ai_summary: string | null;
  created_at: string; // ISO 8601
}

interface RubricSummary {
  id: number;
  title: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('es-ES', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/**
 * Extracts the "owner/repo" part from a GitHub URL so the table column
 * doesn't overflow with the full https://github.com/... path.
 */
function shortRepo(url: string): string {
  try {
    const { pathname } = new URL(url);
    // pathname = "/owner/repo" → strip leading slash
    return pathname.replace(/^\//, '').replace(/\.git$/, '');
  } catch {
    return url;
  }
}

/** Returns Tailwind classes for the score badge colour. */
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

/** Returns Tailwind classes for the status pill. */
function statusClass(status: EvaluationResponse['status']): string {
  switch (status) {
    case 'completed':
      return 'bg-green-100 text-green-700';
    case 'processing':
      return 'bg-blue-100 text-blue-700';
    case 'pending':
      return 'bg-yellow-100 text-yellow-700';
    case 'failed':
      return 'bg-red-100 text-red-700';
    default:
      return 'bg-gray-100 text-gray-500';
  }
}

/** Maps API status values to their Spanish display labels. */
function translateStatus(status: string): string {
  const map: Record<string, string> = {
    pending:    'Pendiente',
    processing: 'Procesando',
    completed:  'Completado',
    failed:     'Fallido',
  };
  return map[status] ?? status;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  // ── Data ──────────────────────────────────────────────────────────────────
  const [evaluations, setEvaluations] = useState<EvaluationResponse[]>([]);
  const [rubrics, setRubrics] = useState<RubricSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const [evalRes, rubricRes] = await Promise.all([
          fetch('/api/v1/evaluations/'),
          fetch('/api/v1/rubrics/'),
        ]);

        if (!evalRes.ok || !rubricRes.ok) throw new Error('Failed to load data');

        const evalJson: { success: boolean; data: EvaluationResponse[] } =
          await evalRes.json();
        const rubricJson: { success: boolean; data: RubricSummary[] } =
          await rubricRes.json();

        if (!evalJson.success || !rubricJson.success)
          throw new Error('API returned success: false');

        setEvaluations(evalJson.data ?? []);
        setRubrics(rubricJson.data ?? []);
      } catch {
        setError(true);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // ── Derived stats ─────────────────────────────────────────────────────────

  /** Total number of evaluations ever created. */
  const totalEvaluations = evaluations.length;

  /** Average score across completed evaluations only. */
  const completed = evaluations.filter(
    (e) => e.status === 'completed' && e.total_score !== null,
  );
  const averageScore =
    completed.length > 0
      ? Math.round(
          (completed.reduce((sum, e) => sum + (e.total_score ?? 0), 0) /
            completed.length) *
            10,
        ) / 10
      : null;

  /**
   * Most-used rubric: the rubric_id that appears most often across all
   * evaluations. Resolved to its title via the rubrics list.
   */
  const mostUsedRubric = (() => {
    if (evaluations.length === 0) return null;
    const freq: Record<number, number> = {};
    for (const e of evaluations) freq[e.rubric_id] = (freq[e.rubric_id] ?? 0) + 1;
    const topId = Number(
      Object.entries(freq).sort((a, b) => b[1] - a[1])[0][0],
    );
    return rubrics.find((r) => r.id === topId)?.title ?? `Rubric #${topId}`;
  })();

  /** Map rubric_id → title for the table column. */
  const rubricMap = Object.fromEntries(rubrics.map((r) => [r.id, r.title]));

  /** Last 5 evaluations sorted by creation date descending. */
  const recentEvaluations = [...evaluations]
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )
    .slice(0, 5);

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col min-h-full bg-gray-50">
      <PageHeader
        title="Dashboard"
        description="Resumen de la actividad de evaluación y resultados recientes"
      />

      <div className="flex-1 px-4 sm:px-6 py-6 sm:py-8 space-y-8 max-w-7xl w-full mx-auto">

        {/* ── Error state ─────────────────────────────────────────────── */}
        {error && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-6 py-4 text-red-700 text-sm">
            Error al cargar los datos. Por favor, recarga la página.
          </div>
        )}

        {/* ── Stat cards ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">

          {/* Total Evaluations */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 flex flex-col gap-3">
            <div className="flex items-start justify-between">
              <div className="p-2 rounded-lg bg-indigo-50">
                <FileText className="w-5 h-5 text-indigo-600" />
              </div>
              <span className="flex items-center gap-1 text-xs font-medium text-green-600">
                <TrendingUp className="w-3.5 h-3.5" />
                Histórico
              </span>
            </div>
            <div>
              <p className="text-sm text-gray-500 mb-1">Total de Evaluaciones</p>
              {loading ? (
                <div className="h-9 w-16 bg-gray-100 rounded animate-pulse" />
              ) : (
                <p className="text-3xl sm:text-4xl font-bold text-gray-900">
                  {totalEvaluations}
                </p>
              )}
            </div>
          </div>

          {/* Average Score */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 flex flex-col gap-3">
            <div className="flex items-start justify-between">
              <div className="p-2 rounded-lg bg-indigo-50">
                <Award className="w-5 h-5 text-indigo-600" />
              </div>
              <span className="flex items-center gap-1 text-xs font-medium text-green-600">
                <TrendingUp className="w-3.5 h-3.5" />
                Solo completadas
              </span>
            </div>
            <div>
              <p className="text-sm text-gray-500 mb-1">Puntuación Media</p>
              {loading ? (
                <div className="h-9 w-20 bg-gray-100 rounded animate-pulse" />
              ) : (
                <p className="text-3xl sm:text-4xl font-bold text-gray-900">
                  {formatScore(averageScore)}
                </p>
              )}
            </div>
          </div>

          {/* Most Used Rubric */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 flex flex-col gap-3">
            <div className="flex items-start justify-between">
              <div className="p-2 rounded-lg bg-indigo-50">
                <BookOpen className="w-5 h-5 text-indigo-600" />
              </div>
              <span className="text-xs font-medium text-gray-400">
                Por uso
              </span>
            </div>
            <div>
              <p className="text-sm text-gray-500 mb-1">Rúbrica Más Usada</p>
              {loading ? (
                <div className="h-9 w-36 bg-gray-100 rounded animate-pulse" />
              ) : (
                <p className="text-xl sm:text-2xl font-bold text-gray-900 leading-tight">
                  {mostUsedRubric ?? '—'}
                </p>
              )}
            </div>
          </div>
        </div>

        {/* ── Recent Evaluations table ─────────────────────────────────── */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          {/* Table header row */}
          <div className="flex items-center justify-between px-4 sm:px-6 py-4 sm:py-5 border-b border-gray-100">
            <div>
              <h2 className="text-base font-semibold text-gray-900">
                Evaluaciones Recientes
              </h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Últimas evaluaciones de proyectos
              </p>
            </div>
            <Link
              href="/past-evaluations"
              className="text-sm font-medium text-indigo-600 hover:text-indigo-700 flex items-center gap-1 transition-colors"
            >
              Ver Todo <ArrowRight className="w-4 h-4" />
            </Link>
          </div>

          {loading ? (
            /* Loading skeleton */
            <div className="divide-y divide-gray-100">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="px-6 py-4 flex items-center gap-4">
                  <div className="h-4 bg-gray-100 rounded w-1/3 animate-pulse" />
                  <div className="h-4 bg-gray-100 rounded w-1/5 animate-pulse ml-auto" />
                  <div className="h-6 bg-gray-100 rounded w-10 animate-pulse" />
                </div>
              ))}
            </div>
          ) : recentEvaluations.length === 0 ? (
            /* Empty state */
            <div className="px-6 py-16 text-center">
              <FileText className="w-10 h-10 text-gray-300 mx-auto mb-3" />
              <p className="text-gray-500 text-sm">Sin evaluaciones todavía.</p>
              <Link
                href="/new-evaluation"
                className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-700"
              >
                Crea tu primera evaluación <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
          ) : (
            /* Table */
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">
                      Repositorio
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider hidden md:table-cell">
                      Rúbrica
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider hidden sm:table-cell">
                      Puntuación
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider hidden lg:table-cell">
                      Fecha
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider hidden sm:table-cell">
                      Estado
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">
                      Acciones
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {recentEvaluations.map((ev) => (
                    <tr
                      key={ev.id}
                      className="hover:bg-gray-50 transition-colors"
                    >
                      {/* Repository */}
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2 min-w-0">
                          <FileText className="w-4 h-4 text-gray-400 shrink-0" />
                          <span className="font-medium text-gray-900 truncate max-w-xs">
                            {shortRepo(ev.repo_url)}
                          </span>
                        </div>
                        {/* On mobile show rubric + status below the repo name */}
                        <div className="mt-1 flex items-center gap-2 md:hidden">
                          <span className="text-xs text-gray-500 truncate">
                            {rubricMap[ev.rubric_id] ?? `#${ev.rubric_id}`}
                          </span>
                          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusClass(ev.status)}`}>
                            {translateStatus(ev.status)}
                          </span>
                        </div>
                      </td>

                      {/* Rubric */}
                      <td className="px-6 py-4 text-gray-500 hidden md:table-cell">
                        {rubricMap[ev.rubric_id] ?? `#${ev.rubric_id}`}
                      </td>

                      {/* Score badge */}
                      <td className="px-6 py-4 hidden sm:table-cell">
                        <span
                          className={`inline-flex items-center justify-center w-10 h-7 rounded-full text-xs font-bold ${scoreBadgeClass(ev.total_score)}`}
                        >
                          {formatScore(ev.total_score)}
                        </span>
                      </td>

                      {/* Date */}
                      <td className="px-6 py-4 text-gray-500 hidden lg:table-cell">
                        {formatDate(ev.created_at)}
                      </td>

                      {/* Status pill */}
                      <td className="px-6 py-4 hidden sm:table-cell">
                        <span
                          className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${statusClass(ev.status)}`}
                        >
                          {translateStatus(ev.status)}
                        </span>
                      </td>

                      {/* Action */}
                      <td className="px-6 py-4">
                        <Link
                          href={`/past-evaluations/${ev.id}`}
                          className="text-indigo-600 hover:text-indigo-700 font-medium transition-colors"
                        >
                          Ver Informe
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── CTA banner ──────────────────────────────────────────────────── */}
        <div className="rounded-xl bg-linear-to-r from-indigo-600 to-violet-600 px-4 sm:px-8 py-4 sm:py-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <p className="text-white font-semibold text-lg">
              ¿Listo para evaluar un nuevo proyecto?
            </p>
            <p className="text-indigo-200 text-sm mt-0.5">
              Inicia una nueva evaluación con IA en pocos clics
            </p>
          </div>
          <Link
            href="/new-evaluation"
            className="shrink-0 inline-flex items-center gap-2 bg-white text-indigo-600 font-semibold text-sm px-5 py-2.5 rounded-lg hover:bg-indigo-50 transition-colors"
          >
              Nueva Evaluación <ArrowRight className="w-4 h-4" />
          </Link>
        </div>

      </div>
    </div>
  );
}
