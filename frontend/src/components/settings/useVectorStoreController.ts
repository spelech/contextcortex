import { useState, useEffect, useCallback } from 'react';
import type { Stats, VectorStoreConfig } from '../../types';

interface ToastApi {
  success: (msg: string) => void;
  error: (msg: string) => void;
}

export function normalizeVsProvider(prov?: string): 'qdrant' | 'pgvector' {
  if (prov === 'pgvector' || prov === 'postgres' || prov === 'postgresql') {
    return 'pgvector';
  }
  return 'qdrant';
}

export function useVectorStoreController(
  stats: Stats | null,
  refreshStats: () => void,
  toast: ToastApi
) {
  const [vectorStore, setVectorStore] = useState<VectorStoreConfig | null>(null);
  const [isLoadingVs, setIsLoadingVs] = useState(false);
  const [vsProvider, setVsProvider] = useState<'qdrant' | 'pgvector'>('qdrant');
  const [vsMode, setVsMode] = useState<'embedded' | 'remote'>('embedded');
  const [vsStoragePath, setVsStoragePath] = useState('data/qdrant_db');
  const [vsUrl, setVsUrl] = useState('http://localhost:6333');
  const [vsCollection, setVsCollection] = useState('knowledge_rag_v1');
  const [isTestingVs, setIsTestingVs] = useState(false);
  const [testFeedback, setTestFeedback] = useState<{ success: boolean; message: string } | null>(null);
  const [isSwitchingVs, setIsSwitchingVs] = useState(false);

  const loadVectorStore = useCallback(async () => {
    setIsLoadingVs(true);
    try {
      const res = await fetch('/admin/api/vector-store');
      if (res.ok) {
        const data: VectorStoreConfig = await res.json();
        setVectorStore(data);
        if (data.provider) setVsProvider(normalizeVsProvider(data.provider));
        if (data.mode) setVsMode(data.mode === 'embedded' ? 'embedded' : 'remote');
        if (data.storage_path) setVsStoragePath(data.storage_path);
        if (data.url !== undefined && data.url !== null) setVsUrl(data.url);
        if (data.collection) setVsCollection(data.collection);
      }
    } catch (e: any) {
      console.error('Failed to load vector store config:', e);
    } finally {
      setIsLoadingVs(false);
    }
  }, []);

  useEffect(() => {
    loadVectorStore();
  }, [loadVectorStore]);

  useEffect(() => {
    if (stats?.vector_store) {
      setVectorStore(stats.vector_store);
      if (stats.vector_store.provider) setVsProvider(normalizeVsProvider(stats.vector_store.provider));
      if (stats.vector_store.mode) setVsMode(stats.vector_store.mode === 'embedded' ? 'embedded' : 'remote');
      if (stats.vector_store.storage_path) setVsStoragePath(stats.vector_store.storage_path);
      if (stats.vector_store.url !== undefined && stats.vector_store.url !== null) setVsUrl(stats.vector_store.url);
      if (stats.vector_store.collection) setVsCollection(stats.vector_store.collection);
    } else if (stats?.vector_store_provider) {
      setVectorStore((prev) =>
        prev
          ? {
              ...prev,
              provider: (stats.vector_store_provider as any) || prev.provider,
              mode: (stats.vector_store_mode as any) || prev.mode,
              collection: stats.vector_store_collection || prev.collection,
            }
          : null
      );
      if (stats.vector_store_provider) setVsProvider(normalizeVsProvider(stats.vector_store_provider));
      if (stats.vector_store_mode) setVsMode(stats.vector_store_mode === 'embedded' ? 'embedded' : 'remote');
      if (stats.vector_store_collection) setVsCollection(stats.vector_store_collection);
    }
  }, [stats]);

  const handleProviderChange = (newProvider: 'qdrant' | 'pgvector') => {
    setVsProvider(newProvider);
    if (newProvider === 'qdrant') {
      if (!vsStoragePath) setVsStoragePath('data/qdrant_db');
      if (!vsUrl || vsUrl.startsWith('postgresql')) setVsUrl('http://localhost:6333');
    } else {
      setVsMode('remote');
      if (!vsUrl || vsUrl === 'http://localhost:6333') {
        setVsUrl('postgresql+psycopg://localhost:5432/contextcortex');
      }
    }
  };

  const handleModeChange = (newMode: 'embedded' | 'remote') => {
    setVsMode(newMode);
    if (newMode === 'embedded' && !vsStoragePath) {
      setVsStoragePath('data/qdrant_db');
    }
    if (newMode === 'remote' && !vsUrl) {
      setVsUrl(
        vsProvider === 'pgvector'
          ? 'postgresql+psycopg://localhost:5432/contextcortex'
          : 'http://localhost:6333'
      );
    }
  };

  const handleTestConnection = async () => {
    setIsTestingVs(true);
    setTestFeedback(null);
    const effectiveMode = vsProvider === 'pgvector' ? 'remote' : vsMode;
    try {
      const payload = {
        provider: vsProvider,
        mode: effectiveMode,
        storage_path: effectiveMode === 'embedded' ? vsStoragePath.trim() : null,
        url: effectiveMode === 'remote' ? vsUrl.trim() || null : null,
        collection: vsCollection.trim() || 'knowledge_rag_v1',
      };
      const res = await fetch('/admin/api/vector-store/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = data.error || data.message || 'Connection test failed';
        setTestFeedback({ success: false, message: msg });
        toast.error('Vector store test: ' + msg);
      } else {
        const msg =
          data.message || (data.success ? 'Vector store connection healthy.' : 'Vector store test failed.');
        setTestFeedback({ success: data.success, message: msg });
        if (data.success) toast.success(msg);
        else toast.error('Vector store test: ' + msg);
      }
    } catch (e: any) {
      setTestFeedback({ success: false, message: e.message });
      toast.error('Vector store test error: ' + e.message);
    } finally {
      setIsTestingVs(false);
    }
  };

  const handleSwitchBackend = async () => {
    const providerName = vsProvider === 'qdrant' ? 'Qdrant' : 'PostgreSQL (pgvector)';
    const effectiveMode = vsProvider === 'pgvector' ? 'remote' : vsMode;
    if (
      !window.confirm(
        `Switch active vector database backend to ${providerName} (${effectiveMode})? Existing embeddings in the old database will remain intact.`
      )
    ) {
      return;
    }
    setIsSwitchingVs(true);
    setTestFeedback(null);
    try {
      const payload = {
        provider: vsProvider,
        mode: effectiveMode,
        storage_path: effectiveMode === 'embedded' ? vsStoragePath.trim() : null,
        url: effectiveMode === 'remote' ? vsUrl.trim() || null : null,
        collection: vsCollection.trim() || 'knowledge_rag_v1',
      };
      const res = await fetch('/admin/api/vector-store/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || data.status === 'error') {
        const msg = data.error || data.message || 'Failed to switch vector database backend';
        setTestFeedback({ success: false, message: msg });
        toast.error('Switch error: ' + msg);
      } else {
        const msg = data.message || `Switched vector backend to ${providerName}`;
        setTestFeedback({ success: true, message: msg });
        toast.success(msg);
        await loadVectorStore();
        refreshStats();
      }
    } catch (e: any) {
      setTestFeedback({ success: false, message: e.message });
      toast.error('Switch error: ' + e.message);
    } finally {
      setIsSwitchingVs(false);
    }
  };

  return {
    vectorStore,
    isLoadingVs,
    vsProvider,
    vsMode,
    vsStoragePath,
    setVsStoragePath,
    vsUrl,
    setVsUrl,
    vsCollection,
    setVsCollection,
    isTestingVs,
    testFeedback,
    isSwitchingVs,
    handleProviderChange,
    handleModeChange,
    handleTestConnection,
    handleSwitchBackend,
  };
}
