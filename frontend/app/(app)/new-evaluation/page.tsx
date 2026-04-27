'use client';

import React, { useState, useEffect } from 'react';
import { Github, Eye, EyeOff } from 'lucide-react';
import {
  Button,
  Input,
  Select,
  FileUpload,
  Card,
  CardContent,
  Alert,
} from '@/components/ui';
import { PageHeader } from '@/components/layout';
import type { SelectOption } from '@/components/ui';
import { uploadBriefingFile, validateFile } from '@/lib/services/file-upload';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AI_PROVIDERS: SelectOption[] = [
  { value: '',       label: 'Predeterminado del servidor (Gemini Vertex)' },
  { value: 'gemini', label: 'Gemini (Google)' },
  { value: 'groq',   label: 'Groq' },
  { value: 'openai', label: 'OpenAI' },
];

const MODELS_BY_PROVIDER: Record<string, SelectOption[]> = {
  gemini: [
    { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
    { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
    { value: 'gemini-2.0-flash-lite', label: 'Gemini 2.0 Flash Lite' },
  ],
  groq: [
    { value: 'llama-3.3-70b-versatile', label: 'LLaMA 3.3 70B' },
    { value: 'llama-3.1-8b-instant', label: 'LLaMA 3.1 8B Instant' },
    { value: 'llama-3.1-70b-versatile', label: 'LLaMA 3.1 70B' },
  ],
  openai: [
    { value: 'gpt-5-mini', label: 'GPT-5 Mini' },
    { value: 'gpt-4.1-mini', label: 'GPT-4.1 Mini' },
    { value: 'gpt-4o', label: 'GPT-4o' },
  ],
};

// Empty values mean "use backend defaults" (Gemini configured server-side).
const DEFAULT_PROVIDER = '';
const DEFAULT_MODEL = '';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RubricOption {
  id: number;
  title: string;
}

interface FormState {
  rubricId: string;
  briefingFile: File | null;
  briefingServerPath: string;
  repoUrl: string;
  provider: string;
  model: string;
  apiKey: string;
}

interface CooldownApiResponse {
  success: boolean;
  data?: {
    remaining_seconds: number;
    cooldown_seconds: number;
    available: boolean;
  };
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function NewEvaluationPage() {
  // Rubrics from API
  const [rubrics, setRubrics] = useState<RubricOption[]>([]);
  const [rubricsLoading, setRubricsLoading] = useState(true);
  const [rubricsError, setRubricsError] = useState(false);

  // Form — empty AI config means the backend default provider/model is used.
  const [form, setForm] = useState<FormState>({
    rubricId: '',
    briefingFile: null,
    briefingServerPath: '',
    repoUrl: '',
    provider: DEFAULT_PROVIDER,
    model: DEFAULT_MODEL,
    apiKey: '',
  });

  // UI
  const [showApiKey, setShowApiKey] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState(false);
  const [defaultProviderCooldownRemaining, setDefaultProviderCooldownRemaining] = useState(0);
  
  // File upload state
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const isGeminiServerMode =
    (form.provider === '' || form.provider === 'gemini') && form.apiKey.trim() === '';

  const fetchDefaultProviderCooldown = async () => {
    try {
      const res = await fetch('/api/v1/evaluations/default-provider/cooldown');
      if (!res.ok) return;
      const payload = await res.json() as CooldownApiResponse;
      if (payload.success && payload.data) {
        setDefaultProviderCooldownRemaining(payload.data.remaining_seconds);
      }
    } catch {
      // Cooldown check is best-effort; form still works with backend-side enforcement.
    }
  };

  const formatRemaining = (seconds: number): string => {
    const mins = Math.floor(seconds / 60).toString().padStart(2, '0');
    const secs = Math.floor(seconds % 60).toString().padStart(2, '0');
    return `${mins}:${secs}`;
  };

  // Load rubrics on mount
  useEffect(() => {
    fetch(`/api/v1/rubrics/`)
      .then((res) => {
        if (!res.ok) throw new Error('Failed to load rubrics');
        return res.json();
      })
      .then((json: { success: boolean; data: RubricOption[] }) => {
        if (!json.success) {
          setRubricsError(true);
          setRubricsLoading(false);
          return;
        }
        setRubrics(json.data ?? []);
        setRubricsLoading(false);
      })
      .catch(() => {
        setRubricsError(true);
        setRubricsLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchDefaultProviderCooldown();
    const interval = setInterval(fetchDefaultProviderCooldown, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (defaultProviderCooldownRemaining <= 0) return;

    const timer = setInterval(() => {
      setDefaultProviderCooldownRemaining((current) => Math.max(0, current - 1));
    }, 1000);

    return () => clearInterval(timer);
  }, [defaultProviderCooldownRemaining]);

  // Model options depend on selected provider
  const modelOptions: SelectOption[] = form.provider
    ? (MODELS_BY_PROVIDER[form.provider] ?? [])
    : [];

  // When provider changes, auto-select the first model for convenience.
  const handleProviderChange = (value: string) => {
    const providerModels = MODELS_BY_PROVIDER[value] ?? [];
    const firstModelValue = providerModels[0]?.value ?? '';
    setForm((prev) => ({ ...prev, provider: value, model: firstModelValue }));
  };

  // Handle file upload when a file is selected
  const handleFileUpload = async (file: File | null) => {
    if (!file) {
      setForm((prev) => ({ ...prev, briefingFile: null, briefingServerPath: '' }));
      setUploadError(null);
      return;
    }

    // Validate file before upload
    const validation = validateFile(file, 5, ['.pdf']);
    if (!validation.isValid) {
      setUploadError(validation.error || null);
      setForm((prev) => ({ ...prev, briefingFile: null, briefingServerPath: '' }));
      return;
    }

    setUploading(true);
    setUploadError(null);

    try {
      const response = await uploadBriefingFile(file);
      
      if (response.success && response.data) {
        setForm((prev) => ({ 
          ...prev, 
          briefingFile: file, 
          briefingServerPath: response.data!.file_path 
        }));
      } else {
        throw new Error(response.message || 'Error al subir el archivo');
      }
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Error al subir el archivo';
      setUploadError(errorMessage);
      setForm((prev) => ({ ...prev, briefingFile: null, briefingServerPath: '' }));
    } finally {
      setUploading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    setSubmitSuccess(false);
    setIsSubmitting(true);

    try {
      // Use the uploaded file path instead of constructing it
      const briefingPath = form.briefingServerPath;

      if (!briefingPath) {
        throw new Error('Por favor sube el briefing antes de enviar');
      }

      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      const apiKey = form.apiKey.trim();

      const payload: Record<string, unknown> = {
        rubric_id: parseInt(form.rubricId, 10),
        repo_url: form.repoUrl,
        briefing_path: briefingPath,
      };

      // Send custom AI configuration when provider+model are selected.
      // If API key is omitted, backend should use provider credentials from .env.
      const hasCustomSelection = form.provider !== '' && form.model !== '';
      if (hasCustomSelection) {
        payload.ai_provider = form.provider;
        payload.ai_model = form.model;
      }

      // Optional BYOK via header.
      if (apiKey) {
        headers['X-API-Key'] = apiKey;
      }

      const res = await fetch('/api/v1/evaluations/', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({})) as {
        success?: boolean;
        message?: string;
        errors?: string[];
        detail?: string;
      };

      if (!res.ok || data.success === false) {
        throw new Error(
          data.message ?? data.errors?.[0] ?? data.detail ?? 'La evaluación falló. Por favor inténtalo de nuevo.'
        );
      }

      setSubmitSuccess(true);
      setForm({ rubricId: '', briefingFile: null, briefingServerPath: '', repoUrl: '', provider: DEFAULT_PROVIDER, model: DEFAULT_MODEL, apiKey: '' });

      if (isGeminiServerMode) {
        fetchDefaultProviderCooldown();
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Unexpected error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const rubricOptions: SelectOption[] = rubrics.map((r) => ({
    value: String(r.id),
    label: r.title,
  }));

  // Provider/model/API key are optional. When omitted, backend default AI config is used.
  // briefingServerPath is set only after a successful upload, so it is the right guard.
  const isFormValid =
    form.rubricId !== '' &&
    form.briefingServerPath !== '' &&
    form.repoUrl.trim() !== '';

  const isDefaultProviderBlocked = isGeminiServerMode && defaultProviderCooldownRemaining > 0;

  return (
    <div className="max-w-3xl mx-auto">
      <PageHeader
        title="Nueva Evaluación"
        description="Configura y ejecuta una evaluación de repositorio con IA"
      />

      {submitSuccess && (
        <Alert
          variant="success"
          message="¡Evaluación iniciada correctamente! Consulta el Dashboard para ver los resultados."
          className="mb-6"
        />
      )}

      {submitError && (
        <Alert
          variant="error"
          message={submitError}
          className="mb-6"
          onDismiss={() => setSubmitError(null)}
        />
      )}

      {uploadError && (
        <Alert
          variant="error"
          message={uploadError}
          className="mb-6"
          onDismiss={() => setUploadError(null)}
        />
      )}

      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-6">

            {/* Evaluation Rubric */}
            <Select
              label="Rúbrica de Evaluación"
              placeholder={rubricsLoading ? 'Cargando rúbricas...' : 'Selecciona una rúbrica...'}
              options={rubricOptions}
              value={form.rubricId}
              onChange={(val) => setForm((prev) => ({ ...prev, rubricId: val }))}
              disabled={rubricsLoading || rubricsError}
              error={
                rubricsError
                  ? 'No se pudieron cargar las rúbricas. ¿Está el backend en ejecución?'
                  : undefined
              }
              fullWidth
            />

            {/* Project Briefing (PDF) */}
            <FileUpload
              label="Briefing del Proyecto (PDF)"
              accept=".pdf"
              maxSize={5}
              onFileSelect={handleFileUpload}
            />

            {/* GitHub Repository URL */}
            <Input
              label="URL del Repositorio de GitHub"
              type="url"
              placeholder="https://github.com/username/repository"
              value={form.repoUrl}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, repoUrl: e.target.value }))
              }
              leftIcon={<Github className="w-4 h-4" />}
              fullWidth
            />

            {/* AI Provider */}
            <Select
              label="Proveedor de IA"
              placeholder="Predeterminado del servidor (Gemini Vertex)"
              options={AI_PROVIDERS}
              value={form.provider}
              onChange={handleProviderChange}
              helperText="Puedes elegir proveedor/modelo sin clave API para usar la configuración del servidor (.env)."
              fullWidth
            />

            {isGeminiServerMode && (
              <Alert
                variant={isDefaultProviderBlocked ? 'warning' : 'info'}
                message={
                  isDefaultProviderBlocked
                    ? `Gemini Vertex predeterminado en cooldown. Disponible en ${formatRemaining(defaultProviderCooldownRemaining)}.`
                    : 'Gemini Vertex predeterminado disponible para una nueva evaluación.'
                }
              />
            )}

            {/* Model */}
            <Select
              label="Modelo"
              placeholder={
                form.provider ? 'Selecciona un modelo...' : 'Selecciona un proveedor primero'
              }
              options={modelOptions}
              value={form.model}
              onChange={(val) => setForm((prev) => ({ ...prev, model: val }))}
              disabled={!form.provider}
              helperText={!form.provider ? 'No es necesario para la configuración predeterminada.' : undefined}
              fullWidth
            />

            {/* API Key — BYOK (optional) */}
            <Input
              label="Clave API (Opcional — BYOK)"
              type={showApiKey ? 'text' : 'password'}
              placeholder="sk-..."
              value={form.apiKey}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, apiKey: e.target.value }))
              }
              helperText="Opcional: si la dejas vacía, se usará la clave configurada en el servidor para el proveedor seleccionado."
              rightIcon={
                <button
                  type="button"
                  onClick={() => setShowApiKey((v) => !v)}
                  className="text-gray-400 hover:text-gray-600 focus:outline-none"
                  aria-label={showApiKey ? 'Ocultar clave API' : 'Mostrar clave API'}
                >
                  {showApiKey ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              }
              fullWidth
            />

            {/* Submit */}
            <Button
              type="submit"
              variant="primary"
              size="lg"
              fullWidth
              disabled={!isFormValid || isSubmitting || isDefaultProviderBlocked}
              isLoading={isSubmitting}
            >
              Ejecutar Evaluación
            </Button>

            {isDefaultProviderBlocked && (
              <p className="text-xs text-amber-700 text-center">
                Debes esperar {formatRemaining(defaultProviderCooldownRemaining)} antes de reutilizar el proveedor predeterminado.
              </p>
            )}

          </form>
        </CardContent>
      </Card>
    </div>
  );
}
