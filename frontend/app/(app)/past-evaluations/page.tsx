'use client';

import React, { useEffect, useState, useMemo, useRef } from 'react';
import Link from 'next/link';
import {
  FileText,
  TrendingUp,
  Calendar,
  Download,
  Search,
  Filter,
  ExternalLink,
  Loader2,
} from 'lucide-react';
import { PageHeader } from '@/components/layout';
import { StatCard } from '@/components/ui/StatCard';

// ---------------------------------------------------------------------------
// Types — mirror the backend API schemas exactly
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
  description: string;
  created_at: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  errors: string[] | null;
  message: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_OPTIONS = [
  { value: 'all',        label: 'Todos los estados' },
  { value: 'completed',  label: 'Completado' },
  { value: 'processing', label: 'Procesando' },
  { value: 'pending',    label: 'Pendiente' },
  { value: 'failed',     label: 'Fallido' },
];

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

/** Formats an ISO date string to "Mon D, YYYY". */
function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('es-ES', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

/**
 * Extracts "owner/repo" from a GitHub URL so columns don't overflow.
 * Falls back to the raw URL if parsing fails.
 */
function shortRepo(url: string): string {
  try {
    const { pathname } = new URL(url);
    return pathname.replace(/^\//, '').replace(/\.git$/, '');
  } catch {
    return url;
  }
}

/** Tailwind classes for the numeric score badge. */
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
function statusPillClass(status: EvaluationResponse['status']): string {
  switch (status) {
    case 'completed':  return 'bg-green-100 text-green-700';
    case 'processing': return 'bg-blue-100 text-blue-700';
    case 'pending':    return 'bg-yellow-100 text-yellow-700';
    case 'failed':     return 'bg-red-100 text-red-700';
    default:           return 'bg-gray-100 text-gray-500';
  }
}

/** Maps status values to Spanish display labels. */
function translateStatus(status: EvaluationResponse['status']): string {
  const map: Record<string, string> = {
    pending:    'Pendiente',
    processing: 'Procesando',
    completed:  'Completado',
    failed:     'Fallido',
  };
  return map[status] ?? status;
}

/**
 * Triggers a CSV file download from a string of CSV content.
 * Works entirely in the browser — no server needed.
 */
function downloadCsv(content: string, filename: string): void {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href     = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PastEvaluationsPage() {
  // ── Data state ────────────────────────────────────────────────────────────
  const [evaluations, setEvaluations] = useState<EvaluationResponse[]>([]);
  const [rubrics,     setRubrics]     = useState<RubricSummary[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState<string | null>(null);

  // ── Filter state ──────────────────────────────────────────────────────────
  const [search,          setSearch]          = useState('');
  const [selectedRubric,  setSelectedRubric]  = useState('all');
  const [selectedStatus,  setSelectedStatus]  = useState('all');

  // Use relative paths — this is a client-only component ('use client') so
  // all fetches happen in the browser where relative URLs resolve correctly.
  // Consistent with rubrics/page.tsx and dashboard/page.tsx.
  const apiUrl = '';

  // ── Fetch both resources in parallel on mount ─────────────────────────────
  useEffect(() => {
    let cancelled = false;

    async function loadData() {
      setLoading(true);
      setError(null);

      try {
        const [evalRes, rubricRes] = await Promise.all([
          fetch(`${apiUrl}/api/v1/evaluations/`),
          fetch(`${apiUrl}/api/v1/rubrics/`),
        ]);

        if (!evalRes.ok)   throw new Error(`Failed to load evaluations (${evalRes.status})`);
        if (!rubricRes.ok) throw new Error(`Failed to load rubrics (${rubricRes.status})`);

        const [evalJson, rubricJson]: [
          ApiResponse<EvaluationResponse[]>,
          ApiResponse<RubricSummary[]>,
        ] = await Promise.all([evalRes.json(), rubricRes.json()]);

        if (!evalJson.success)   throw new Error(evalJson.message   || 'Failed to load evaluations');
        if (!rubricJson.success) throw new Error(rubricJson.message || 'Failed to load rubrics');

        if (!cancelled) {
          // Sort newest first
          setEvaluations(
            [...evalJson.data].sort(
              (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
            ),
          );
          setRubrics(rubricJson.data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Unexpected error');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadData();
    return () => { cancelled = true; };
  }, [apiUrl]);

  // ── Keep a ref to the current evaluations list ───────────────────────────
  // Used inside the polling interval so we can check for active statuses
  // without adding `evaluations` to the effect’s dependency array.
  // Without this, every setEvaluations() call would restart the 5-second
  // countdown (interval teardown + setup on each response).
  const evaluationsRef = useRef<EvaluationResponse[]>([]);
  useEffect(() => { evaluationsRef.current = evaluations; }, [evaluations]);

  // ── Poll for pending / processing evaluations every 5 s ───────────────────
  // Starts once after the initial load completes. The interval checks the ref
  // on each tick and skips the fetch when no evaluation is still in-flight.
  const POLL_INTERVAL_MS = 5_000;

  useEffect(() => {
    // Do not start polling while the initial load is still running.
    if (loading) return;

    const interval = setInterval(async () => {
      // Check the ref — no dependency on `evaluations` state needed.
      const hasActive = evaluationsRef.current.some(
        (e) => e.status === 'pending' || e.status === 'processing',
      );
      if (!hasActive) return;

      try {
        const res = await fetch(`${apiUrl}/api/v1/evaluations/`);
        if (!res.ok) return;
        const json: ApiResponse<EvaluationResponse[]> = await res.json();
        if (!json.success) return;

        // Merge incoming data into the existing list:
        // - Replace changed entries in-place (preserves order)
        // - Append any brand-new evaluations that weren’t there before
        setEvaluations((prev) => {
          const incoming = Object.fromEntries(json.data.map((e) => [e.id, e]));
          const prevIds  = new Set(prev.map((e) => e.id));
          const merged   = prev.map((e) => incoming[e.id] ?? e);
          const added    = json.data.filter((e) => !prevIds.has(e.id));
          return [...merged, ...added].sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
          );
        });
      } catch {
        // Silently ignore polling errors — non-critical background update.
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  // Only restart the interval when the initial load flag flips (true → false).
  // `evaluations` is intentionally omitted — read via ref to avoid reset loop.
  }, [loading, apiUrl]);

  // ── Derived: rubric lookup map ─────────────────────────────────────────────
  const rubricMap = useMemo(
    () => Object.fromEntries(rubrics.map((r) => [r.id, r.title])),
    [rubrics],
  );

  // ── Derived: rubric dropdown options (only rubrics that appear in results) ─
  const rubricOptions = useMemo(() => {
    const usedIds = new Set(evaluations.map((e) => e.rubric_id));
    return [
      { value: 'all', label: 'Todas las rúbricas' },
      ...rubrics
        .filter((r) => usedIds.has(r.id))
        .map((r) => ({ value: String(r.id), label: r.title })),
    ];
  }, [evaluations, rubrics]);

  // ── Derived: filtered evaluations ─────────────────────────────────────────
  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();

    return evaluations.filter((ev) => {
      // Text search: repo URL or rubric name
      if (q) {
        const rubricName = (rubricMap[ev.rubric_id] ?? '').toLowerCase();
        const repo       = ev.repo_url.toLowerCase();
        if (!repo.includes(q) && !rubricName.includes(q)) return false;
      }

      // Rubric filter
      if (selectedRubric !== 'all' && String(ev.rubric_id) !== selectedRubric) return false;

      // Status filter
      if (selectedStatus !== 'all' && ev.status !== selectedStatus) return false;

      return true;
    });
  }, [evaluations, rubricMap, search, selectedRubric, selectedStatus]);

  // ── Derived: stats (always based on ALL evaluations, not filtered) ─────────
  const stats = useMemo(() => {
    const total = evaluations.length;

    const completed = evaluations.filter(
      (e) => e.status === 'completed' && e.total_score !== null,
    );
    const avgScore =
      completed.length > 0
        ? Math.round(
            (completed.reduce((sum, e) => sum + (e.total_score ?? 0), 0) / completed.length) * 10,
          ) / 10
        : null;

    const now       = new Date();
    const thisMonth = evaluations.filter((e) => {
      const d = new Date(e.created_at);
      return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
    }).length;

    return { total, avgScore, thisMonth };
  }, [evaluations]);

  // ── CSV export ────────────────────────────────────────────────────────────
  function handleExportCsv() {
    const header = ['ID', 'Repository', 'Rubric', 'Score', 'Status', 'Date'];
    const rows   = filtered.map((ev) => [
      ev.id,
      ev.repo_url,
      rubricMap[ev.rubric_id] ?? `Rubric #${ev.rubric_id}`,
      ev.total_score !== null ? formatScore(ev.total_score) : '',
      ev.status,
      formatDate(ev.created_at),
    ]);

    const csv = [header, ...rows]
      .map((row) => row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','))
      .join('\n');

    downloadCsv(csv, `evaluations-${new Date().toISOString().slice(0, 10)}.csv`);
  }

  // ── Render ──────────────────────────────────────────────────────────────––

  return (
    <div className="flex flex-col min-h-full bg-gray-50">
      <PageHeader
        title="Evaluaciones Pasadas"
        description="Historial de todas las evaluaciones de repositorios con resultados detallados"
      />

      <div className="flex-1 px-4 sm:px-6 py-6 sm:py-8 space-y-8 max-w-7xl w-full mx-auto">

        {/* ── Error banner ─────────────────────────────────────────────── */}
        {error && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-6 py-4 text-red-700 text-sm">
            {error}
          </div>
        )}

        {/* ── Stat cards ──────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          {loading ? (
            <>
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-28 bg-white rounded-xl border border-gray-200 animate-pulse" />
              ))}
            </>
          ) : (
            <>
              <StatCard
                title="Total de Evaluaciones"
                value={stats.total}
                icon={FileText}
                iconColor="text-indigo-600"
              />
              <StatCard
                title="Puntuación Media"
                value={stats.avgScore !== null ? stats.avgScore : '—'}
                icon={TrendingUp}
                iconColor="text-green-600"
              />
              <StatCard
                title="Este Mes"
                value={stats.thisMonth}
                icon={Calendar}
                iconColor="text-violet-600"
              />
            </>
          )}
        </div>

        {/* ── Filters + table card ─────────────────────────────────────── */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">

          {/* Filter bar */}
          <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-100 flex flex-col sm:flex-row gap-3">
            {/* Search */}
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <input
                type="text"
                placeholder="Buscar por repositorio o rúbrica..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 bg-gray-50 placeholder:text-gray-400"
              />
            </div>

            {/* Rubric filter */}
            <div className="relative">
              <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <select
                value={selectedRubric}
                onChange={(e) => setSelectedRubric(e.target.value)}
                className="pl-9 pr-8 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 bg-gray-50 appearance-none cursor-pointer min-w-40"
              >
                {rubricOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>

            {/* Status filter */}
            <div className="relative">
              <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <select
                value={selectedStatus}
                onChange={(e) => setSelectedStatus(e.target.value)}
                className="pl-9 pr-8 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 bg-gray-50 appearance-none cursor-pointer min-w-36"
              >
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Table header row */}
          <div className="px-4 sm:px-6 py-3 border-b border-gray-100 flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <p className="text-base font-semibold text-gray-900">Historial de Evaluaciones</p>
                {/* Live indicator — shown while any evaluation is still running */}
                {!loading && evaluations.some((e) => e.status === 'pending' || e.status === 'processing') && (
                  <span className="inline-flex items-center gap-1 text-xs text-blue-600 bg-blue-50 border border-blue-100 rounded-full px-2 py-0.5">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    En vivo
                  </span>
                )}
              </div>
              {!loading && (
                <p className="text-xs text-gray-500 mt-0.5">
                  Mostrando {filtered.length} de {evaluations.length} evaluación{evaluations.length !== 1 ? 'es' : ''}
                </p>
              )}
            </div>
            <button
              onClick={handleExportCsv}
              disabled={loading || filtered.length === 0}
              className="flex items-center gap-1.5 text-sm text-gray-600 border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Download className="w-4 h-4" />
              Exportar CSV
            </button>
          </div>

          {/* ── Loading skeleton ──────────────────────────────────────── */}
          {loading && (
            <div className="divide-y divide-gray-100">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="px-6 py-4 flex items-center gap-4 animate-pulse">
                  <div className="w-5 h-5 rounded bg-gray-100 shrink-0" />
                  <div className="flex-1 space-y-2">
                    <div className="h-3.5 bg-gray-100 rounded w-56" />
                    <div className="h-3 bg-gray-100 rounded w-32" />
                  </div>
                  <div className="h-3.5 bg-gray-100 rounded w-28 hidden md:block" />
                  <div className="h-7 w-10 bg-gray-100 rounded-full hidden sm:block" />
                  <div className="h-3.5 bg-gray-100 rounded w-20 hidden lg:block" />
                  <div className="h-5 w-20 bg-gray-100 rounded-full hidden sm:block" />
                  <div className="h-3.5 bg-gray-100 rounded w-20" />
                </div>
              ))}
            </div>
          )}

          {/* ── Empty state ───────────────────────────────────────────── */}
          {!loading && evaluations.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center px-6">
              <FileText className="w-12 h-12 text-gray-200 mb-4" />
              <p className="text-base font-semibold text-gray-700">Sin evaluaciones todavía</p>
              <p className="text-sm text-gray-500 mt-1 max-w-xs">
                Ejecuta tu primera evaluación para ver los resultados aquí.
              </p>
              <Link
                href="/new-evaluation"
                className="mt-5 inline-flex items-center gap-2 bg-indigo-600 text-white text-sm font-medium px-5 py-2 rounded-lg hover:bg-indigo-700 transition-colors"
              >
                Iniciar una Evaluación
              </Link>
            </div>
          )}

          {/* ── No results after filtering ────────────────────────────── */}
          {!loading && evaluations.length > 0 && filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center px-6">
              <Search className="w-10 h-10 text-gray-200 mb-4" />
              <p className="text-base font-semibold text-gray-700">Sin resultados encontrados</p>
              <p className="text-sm text-gray-500 mt-1">
                Intenta ajustar la búsqueda o los filtros.
              </p>
              <button
                onClick={() => { setSearch(''); setSelectedRubric('all'); setSelectedStatus('all'); }}
                className="mt-4 text-sm text-indigo-600 hover:underline"
              >
                Limpiar todos los filtros
              </button>
            </div>
          )}

          {/* ── Table ────────────────────────────────────────────────── */}
          {!loading && filtered.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <th className="text-left px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      Repositorio
                    </th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">
                      Rúbrica
                    </th>
                    <th className="text-center px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden sm:table-cell">
                      Puntuación
                    </th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden lg:table-cell">
                      Fecha
                    </th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden sm:table-cell">
                      Estado
                    </th>
                    <th className="text-right px-6 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      Acciones
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {filtered.map((ev) => (
                    <tr key={ev.id} className="hover:bg-gray-50 transition-colors">
                      {/* Repository */}
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2 min-w-0">
                          <FileText className="w-4 h-4 text-gray-400 shrink-0" />
                          <span
                            className="font-medium text-gray-900 truncate max-w-xs"
                            title={ev.repo_url}
                          >
                            {shortRepo(ev.repo_url)}
                          </span>
                        </div>
                        {/* On mobile, show rubric + status below the repo */}
                        <div className="mt-1 flex items-center gap-2 md:hidden">
                          <span className="text-xs text-gray-500">
                            {rubricMap[ev.rubric_id] ?? `Rubric #${ev.rubric_id}`}
                          </span>
                          <span
                            className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full ${statusPillClass(ev.status)}`}
                          >
                            {translateStatus(ev.status)}
                          </span>
                        </div>
                      </td>

                      {/* Rubric */}
                      <td className="px-4 py-4 text-gray-600 hidden md:table-cell">
                        <span className="truncate max-w-50 block" title={rubricMap[ev.rubric_id]}>
                          {rubricMap[ev.rubric_id] ?? `Rubric #${ev.rubric_id}`}
                        </span>
                      </td>

                      {/* Score badge */}
                      <td className="px-4 py-4 text-center hidden sm:table-cell">
                        <span
                          className={`inline-flex items-center justify-center w-10 h-10 rounded-full text-sm font-bold ${scoreBadgeClass(ev.total_score)}`}
                        >
                          {formatScore(ev.total_score)}
                        </span>
                      </td>

                      {/* Date */}
                      <td className="px-4 py-4 text-gray-500 hidden lg:table-cell whitespace-nowrap">
                        {formatDate(ev.created_at)}
                      </td>

                      {/* Status pill */}
                      <td className="px-4 py-4 hidden sm:table-cell">
                        <span
                          className={`inline-block text-xs font-medium px-2.5 py-1 rounded-full ${statusPillClass(ev.status)}`}
                        >
                          {translateStatus(ev.status)}
                        </span>
                      </td>

                      {/* Actions */}
                      <td className="px-6 py-4 text-right">
                        <Link
                          href={`/past-evaluations/${ev.id}`}
                          className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
                        >
                          Ver Informe
                          <ExternalLink className="w-3.5 h-3.5" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
