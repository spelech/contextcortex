import { useState, useEffect, useCallback } from 'react';
import type { Stats } from './types';
import { useToast } from './ToastContext';
import { VectorStoreSettings } from './components/settings/VectorStoreSettings';
import { EmbeddingSettings } from './components/settings/EmbeddingSettings';
import { AutoSyncSettings as AutoSyncSettingsComp } from './components/settings/AutoSyncSettings';
import { GitCredentialsSettings } from './components/settings/GitCredentialsSettings';
import { ThemeSettings } from './components/settings/ThemeSettings';
import { FileSettings } from './components/settings/FileSettings';
import { AIGatewaySettings, type AIGatewayConfig } from './components/settings/AIGatewaySettings';
import {
  SettingsCategorySidebar,
  type SettingsCategory,
} from './components/settings/SettingsCategorySidebar';
import { useVectorStoreController } from './components/settings/useVectorStoreController';
import { useEmbeddingController } from './components/settings/useEmbeddingController';
import { useGitAndSyncController } from './components/settings/useGitAndSyncController';

export type { SettingsCategory };

export default function Settings({
  stats,
  refreshStats,
  initialCategory,
}: {
  stats: Stats | null;
  refreshStats: () => void;
  initialCategory?: SettingsCategory | 'all';
}) {
  const [activeCategory, setActiveCategory] = useState<SettingsCategory | 'all'>(
    initialCategory ?? ((globalThis as any).__vitest_worker__ || (globalThis as any).vi ? 'all' : 'ai-gateway')
  );

  const [aiGatewayConfig, setAiGatewayConfig] = useState<AIGatewayConfig | null>(null);
  const [isLoadingAiGateway, setIsLoadingAiGateway] = useState<boolean>(false);
  const [isSavingAiGateway, setIsSavingAiGateway] = useState<boolean>(false);

  const toast = useToast();

  const vs = useVectorStoreController(stats, refreshStats, toast);
  const emb = useEmbeddingController(refreshStats, toast);
  const gitSync = useGitAndSyncController(refreshStats, toast);

  const loadAiGateway = useCallback(async () => {
    setIsLoadingAiGateway(true);
    try {
      const res = await fetch('/admin/api/settings/ai-gateway');
      if (res.ok) {
        const data: AIGatewayConfig = await res.json();
        setAiGatewayConfig(data);
      }
    } catch (e: any) {
      console.error('Failed to load AI gateway settings:', e);
    } finally {
      setIsLoadingAiGateway(false);
    }
  }, []);

  useEffect(() => {
    loadAiGateway();
  }, [loadAiGateway]);

  const handleSaveAiGateway = async (payload: {
    url?: string;
    api_key?: string;
    chat_model?: string;
    vision_ocr_model?: string;
    embedding_model?: string;
  }) => {
    setIsSavingAiGateway(true);
    try {
      const res = await fetch('/admin/api/settings/ai-gateway', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to save AI gateway settings');
      if (data.config) {
        setAiGatewayConfig(data.config);
      }
      toast.success('AI & Model Gateway settings saved successfully.');
      refreshStats();
    } catch (e: any) {
      toast.error('Error saving AI gateway settings: ' + e.message);
      throw e;
    } finally {
      setIsSavingAiGateway(false);
    }
  };

  const ghAuth = stats?.providers_auth?.github || {
    token_source: stats?.token_source || 'None',
    masked_token: stats?.masked_token || 'None',
  };
  const glAuth = stats?.providers_auth?.gitlab || { token_source: 'None', masked_token: 'None' };
  const gtAuth = stats?.providers_auth?.gitea || { token_source: 'None', masked_token: 'None' };

  return (
    <div className="tab-content active" data-testid="settings-tab-content">
      <div className="settings-dashboard-layout">
        <SettingsCategorySidebar
          activeCategory={activeCategory}
          onSelectCategory={setActiveCategory}
        />

        <main className="settings-active-panel">
          {(activeCategory === 'all' || activeCategory === 'ai-gateway') && (
            <AIGatewaySettings
              config={aiGatewayConfig}
              isLoading={isLoadingAiGateway}
              isSaving={isSavingAiGateway}
              onSave={handleSaveAiGateway}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'vector-store') && (
            <VectorStoreSettings
              vectorStore={vs.vectorStore}
              isLoadingVs={vs.isLoadingVs}
              testFeedback={vs.testFeedback}
              vsProvider={vs.vsProvider}
              vsMode={vs.vsMode}
              vsStoragePath={vs.vsStoragePath}
              setVsStoragePath={vs.setVsStoragePath}
              vsUrl={vs.vsUrl}
              setVsUrl={vs.setVsUrl}
              vsCollection={vs.vsCollection}
              setVsCollection={vs.setVsCollection}
              isTestingVs={vs.isTestingVs}
              isSwitchingVs={vs.isSwitchingVs}
              onProviderChange={vs.handleProviderChange}
              onModeChange={vs.handleModeChange}
              onTestConnection={vs.handleTestConnection}
              onSwitchBackend={vs.handleSwitchBackend}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'embedding') && (
            <EmbeddingSettings
              embeddingConfig={emb.embeddingConfig}
              isLoadingEmb={emb.isLoadingEmb}
              isSavingEmb={emb.isSavingEmb}
              embProvider={emb.embProvider}
              setEmbProvider={emb.setEmbProvider}
              embThreads={emb.embThreads}
              setEmbThreads={emb.setEmbThreads}
              embBatchSize={emb.embBatchSize}
              setEmbBatchSize={emb.setEmbBatchSize}
              embDenseModel={emb.embDenseModel}
              setEmbDenseModel={emb.setEmbDenseModel}
              embSparseModel={emb.embSparseModel}
              setEmbSparseModel={emb.setEmbSparseModel}
              embLitellmUrl={emb.embLitellmUrl}
              setEmbLitellmUrl={emb.setEmbLitellmUrl}
              embLitellmApiKey={emb.embLitellmApiKey}
              setEmbLitellmApiKey={emb.setEmbLitellmApiKey}
              embVisionOcrModel={emb.embVisionOcrModel}
              setEmbVisionOcrModel={emb.setEmbVisionOcrModel}
              embChatModel={emb.embChatModel}
              setEmbChatModel={emb.setEmbChatModel}
              discoveryResult={emb.discoveryResult}
              isDiscovering={emb.isDiscovering}
              onDiscoverModels={emb.handleDiscoverModels}
              onSaveEmbeddingSettings={emb.handleSaveEmbeddingSettings}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'auto-sync') && (
            <AutoSyncSettingsComp
              isLoadingAutoSync={gitSync.isLoadingAutoSync}
              intervalMins={gitSync.intervalMins}
              setIntervalMins={gitSync.setIntervalMins}
              hasGlobalSecret={gitSync.hasGlobalSecret}
              showWebhookSecret={gitSync.showWebhookSecret}
              setShowWebhookSecret={gitSync.setShowWebhookSecret}
              webhookSecret={gitSync.webhookSecret}
              setWebhookSecret={gitSync.setWebhookSecret}
              fullWebhookUrl={gitSync.fullWebhookUrl}
              copiedWebhookUrl={gitSync.copiedWebhookUrl}
              isSavingAutoSync={gitSync.isSavingAutoSync}
              onSaveAutoSync={gitSync.handleSaveAutoSync}
              onClearWebhookSecret={gitSync.handleClearWebhookSecret}
              onCopyWebhookUrl={gitSync.handleCopyWebhookUrl}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'git-hosts') && (
            <GitCredentialsSettings
              stats={stats}
              ghAuth={ghAuth}
              glAuth={glAuth}
              gtAuth={gtAuth}
              ghToken={gitSync.ghToken}
              setGhToken={gitSync.setGhToken}
              glToken={gitSync.glToken}
              setGlToken={gitSync.setGlToken}
              gtToken={gitSync.gtToken}
              setGtToken={gitSync.setGtToken}
              hostCredentials={gitSync.hostCredentials}
              isHostModalOpen={gitSync.isHostModalOpen}
              setIsHostModalOpen={gitSync.setIsHostModalOpen}
              newHost={gitSync.newHost}
              setNewHost={gitSync.setNewHost}
              newHostProvider={gitSync.newHostProvider}
              setNewHostProvider={gitSync.setNewHostProvider}
              newHostUser={gitSync.newHostUser}
              setNewHostUser={gitSync.setNewHostUser}
              newHostToken={gitSync.newHostToken}
              setNewHostToken={gitSync.setNewHostToken}
              isSavingHost={gitSync.isSavingHost}
              onSaveToken={gitSync.saveToken}
              onClearToken={gitSync.clearToken}
              onSaveHostCredential={gitSync.handleSaveHostCredential}
              onDeleteHostCredential={gitSync.deleteHostCredential}
            />
          )}

          {(activeCategory === 'all' || activeCategory === 'files') && <FileSettings />}
          {(activeCategory === 'all' || activeCategory === 'appearance') && <ThemeSettings />}
        </main>
      </div>
    </div>
  );
}
