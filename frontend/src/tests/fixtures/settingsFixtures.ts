import { vi } from 'vitest';
import type { Stats, GitHostCredential, VectorStoreConfig, EmbeddingConfig } from '../../types';

export const mockStats: Stats = {
  repos_count: 2,
  symbols_count: 100,
  files_count: 5,
  points_count: 200,
  last_indexed: '2026-08-17',
  is_indexing: false,
  token_source: 'Database',
  masked_token: 'ghp_****5678',
  rate_limit: { remaining: 4950, limit: 5000 },
  providers_auth: {
    github: { token_source: 'Database', masked_token: 'ghp_****5678' },
    gitlab: { token_source: 'Environment', masked_token: 'glpat_****4321' },
    gitea: { token_source: 'Database', masked_token: 'gitea_****9876' }
  },
  vector_store_provider: 'qdrant',
  vector_store_mode: 'embedded',
  vector_store_collection: 'knowledge_rag_v1'
};

export const mockVectorStoreConfig: VectorStoreConfig = {
  provider: 'qdrant',
  mode: 'embedded',
  storage_path: 'data/qdrant_db',
  url: 'http://localhost:6333',
  collection: 'knowledge_rag_v1',
  healthy: true,
  health_message: 'Collection knowledge_rag_v1 is healthy and operational',
  points_count: 1250,
  stats: { points_count: 1250, vector_dimension: 384 }
};

export const mockEmbeddingConfig: EmbeddingConfig = {
  provider: 'local',
  dense_model: 'BAAI/bge-small-en-v1.5',
  sparse_model: 'Qdrant/bm25',
  threads: 2,
  batch_size: 32,
  system_cpus: 8,
  system_memory_gb: 16.0,
  litellm_url: 'http://litellm:4000/v1',
  vision_ocr_model: 'gemini-2.5-flash',
  chat_model: 'gemini-2.5-flash',
};

export const mockHostCreds: GitHostCredential[] = [
  {
    id: 1,
    host: 'gitlab.enterprise.internal',
    provider: 'gitlab',
    auth_user: 'gitlab-ci-token',
    masked_token: 'glpa...9999',
    added_at: '2026-08-17 12:00:00'
  },
  {
    id: 2,
    host: 'http://git.lan:3000',
    provider: 'gitea',
    auth_user: undefined,
    masked_token: 'gt_s...1111',
    added_at: '2026-08-17 12:05:00'
  }
];

export const mockAutoSyncSettings = {
  interval_mins: 15,
  webhook_url: '/api/webhooks/git',
  has_global_secret: false
};

export function installDefaultSettingsFetchMocks(): void {
  (globalThis as any).fetch = vi.fn().mockImplementation((url: string) => {
    if (url === '/admin/api/settings/hosts') {
      return Promise.resolve({ ok: true, json: async () => mockHostCreds });
    }
    if (url === '/admin/api/vector-store') {
      return Promise.resolve({ ok: true, json: async () => mockVectorStoreConfig });
    }
    if (url === '/admin/api/settings/auto-sync') {
      return Promise.resolve({ ok: true, json: async () => mockAutoSyncSettings });
    }
    if (url === '/admin/api/settings/embedding') {
      return Promise.resolve({ ok: true, json: async () => mockEmbeddingConfig });
    }
    return Promise.resolve({ ok: true, json: async () => ({}) });
  });
}
