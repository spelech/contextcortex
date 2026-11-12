import { useState, useEffect, useCallback } from 'react';
import type { FormEvent } from 'react';
import type { EmbeddingConfig, ModelDiscoveryResult } from '../../types';

interface ToastApi {
  success: (msg: string) => void;
  error: (msg: string) => void;
  info: (msg: string) => void;
}

export function useEmbeddingController(refreshStats: () => void, toast: ToastApi) {
  const [embeddingConfig, setEmbeddingConfig] = useState<EmbeddingConfig | null>(null);
  const [isLoadingEmb, setIsLoadingEmb] = useState(false);
  const [isSavingEmb, setIsSavingEmb] = useState(false);
  const [embProvider, setEmbProvider] = useState<'local' | 'api'>('api');
  const [embThreads, setEmbThreads] = useState<number>(2);
  const [embBatchSize, setEmbBatchSize] = useState<number>(32);
  const [embDenseModel, setEmbDenseModel] = useState('BAAI/bge-small-en-v1.5');
  const [embSparseModel, setEmbSparseModel] = useState('Qdrant/bm25');
  const [embLitellmUrl, setEmbLitellmUrl] = useState('http://litellm:4000/v1');
  const [embLitellmApiKey, setEmbLitellmApiKey] = useState('');
  const [embVisionOcrModel, setEmbVisionOcrModel] = useState('');
  const [embChatModel, setEmbChatModel] = useState('');
  const [discoveryResult, setDiscoveryResult] = useState<ModelDiscoveryResult | null>(null);
  const [isDiscovering, setIsDiscovering] = useState(false);

  const loadEmbeddingConfig = useCallback(async () => {
    setIsLoadingEmb(true);
    try {
      const res = await fetch('/admin/api/settings/embedding');
      if (res.ok) {
        const data: EmbeddingConfig = await res.json();
        setEmbeddingConfig(data);
        setEmbProvider('api');
        if (typeof data.threads === 'number') setEmbThreads(data.threads);
        if (typeof data.batch_size === 'number') setEmbBatchSize(data.batch_size);
        if (data.dense_model) setEmbDenseModel(data.dense_model);
        if (data.sparse_model) setEmbSparseModel(data.sparse_model);
        if (data.litellm_url) setEmbLitellmUrl(data.litellm_url);
        if (data.litellm_api_key) setEmbLitellmApiKey(data.litellm_api_key);
        if (data.vision_ocr_model) setEmbVisionOcrModel(data.vision_ocr_model);
        if (data.chat_model) setEmbChatModel(data.chat_model);
      }
    } catch (e: any) {
      console.error('Failed to load embedding config:', e);
    } finally {
      setIsLoadingEmb(false);
    }
  }, []);

  useEffect(() => {
    loadEmbeddingConfig();
  }, [loadEmbeddingConfig]);

  const handleDiscoverModels = async () => {
    setIsDiscovering(true);
    try {
      const params = new URLSearchParams();
      if (embLitellmUrl) params.set('url', embLitellmUrl);
      if (embLitellmApiKey.trim()) params.set('api_key', embLitellmApiKey.trim());
      const res = await fetch(`/admin/api/models/discover?${params.toString()}`);
      const data: ModelDiscoveryResult = await res.json();
      setDiscoveryResult(data);
      if (data.status === 'success') {
        if (!embChatModel && Array.isArray(data.chat_models) && data.chat_models.length > 0) {
          const firstChat =
            typeof data.chat_models[0] === 'string'
              ? data.chat_models[0]
              : (data.chat_models[0] as any)?.id || '';
          if (firstChat) setEmbChatModel(firstChat);
        }
        if (!embVisionOcrModel && Array.isArray(data.vision_models) && data.vision_models.length > 0) {
          const firstVision =
            typeof data.vision_models[0] === 'string'
              ? data.vision_models[0]
              : (data.vision_models[0] as any)?.id || '';
          if (firstVision) setEmbVisionOcrModel(firstVision);
        }
        toast.success(`Discovered ${data.total_models} models from OpenAI-compatible endpoint`);
      } else {
        toast.error(data.message || 'Model discovery returned an error');
      }
    } catch (e: any) {
      toast.error('Failed to discover models: ' + e.message);
      setDiscoveryResult({
        status: 'error',
        total_models: 0,
        models: [],
        embedding_models: [],
        vision_models: [],
        chat_models: [],
        message: e.message,
      });
    } finally {
      setIsDiscovering(false);
    }
  };

  const handleSaveEmbeddingSettings = async (e: FormEvent) => {
    e.preventDefault();
    setIsSavingEmb(true);
    try {
      const payload: Record<string, unknown> = {
        provider: 'api' as const,
        threads: Number(embThreads),
        batch_size: Number(embBatchSize),
        dense_model: embDenseModel.trim() || undefined,
        sparse_model: embSparseModel.trim() || undefined,
        vision_ocr_model: embVisionOcrModel.trim() || undefined,
        chat_model: embChatModel.trim() || undefined,
      };
      if (embLitellmUrl.trim() && embLitellmUrl.trim() !== (embeddingConfig?.litellm_url || '')) {
        payload.litellm_url = embLitellmUrl.trim();
      }
      if (embLitellmApiKey.trim()) {
        payload.litellm_api_key = embLitellmApiKey.trim();
      }

      const res = await fetch('/admin/api/settings/embedding', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (!res.ok) {
        const errMsg = data.error || data.message || 'Failed to save embedding settings';
        if (
          res.status === 400 &&
          (errMsg.includes('rebuild_index') || errMsg.includes('Explicit rebuild confirmation'))
        ) {
          const confirmed = window.confirm(
            `${errMsg}\n\nProceed with clearing existing vector points and rebuilding the index now?`
          );
          if (!confirmed) {
            toast.info('Embedding model change cancelled');
            return;
          }
          const rebuildRes = await fetch('/admin/api/settings/embedding', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...payload, rebuild_index: true }),
          });
          const rebuildData = await rebuildRes.json();
          if (!rebuildRes.ok) {
            throw new Error(rebuildData.error || rebuildData.message || 'Failed to rebuild embedding index');
          }
          if (rebuildData.config) setEmbeddingConfig(rebuildData.config);
          toast.success('Embedding model updated and index rebuild started');
          refreshStats();
          return;
        }
        throw new Error(errMsg);
      }

      if (data.config) {
        setEmbeddingConfig(data.config);
      }
      toast.success('Embedding resource limits updated successfully');
      refreshStats();
    } catch (e: any) {
      toast.error('Error saving embedding settings: ' + e.message);
    } finally {
      setIsSavingEmb(false);
    }
  };

  return {
    embeddingConfig,
    isLoadingEmb,
    isSavingEmb,
    embProvider,
    setEmbProvider,
    embThreads,
    setEmbThreads,
    embBatchSize,
    setEmbBatchSize,
    embDenseModel,
    setEmbDenseModel,
    embSparseModel,
    setEmbSparseModel,
    embLitellmUrl,
    setEmbLitellmUrl,
    embLitellmApiKey,
    setEmbLitellmApiKey,
    embVisionOcrModel,
    setEmbVisionOcrModel,
    embChatModel,
    setEmbChatModel,
    discoveryResult,
    isDiscovering,
    handleDiscoverModels,
    handleSaveEmbeddingSettings,
  };
}
