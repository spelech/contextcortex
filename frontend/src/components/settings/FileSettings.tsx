import { useState, useEffect } from 'react';
import type { FormEvent } from 'react';
import type { FileSettings as FileSettingsType } from '../../types';
import { useToast } from '../../ToastContext';

export function FileSettings() {
  const [settings, setSettings] = useState<FileSettingsType>({
    summary_enabled: true,
    summary_threshold_kb: 500,
    summary_max_file_size_mb: 10,
    read_file_max_lines: 2000,
    summary_chat_model: 'gemini-2.5-flash',
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const toast = useToast();

  const loadSettings = async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/admin/api/settings/files');
      if (res.ok) {
        const data = await res.json();
        setSettings({
          summary_enabled: data.summary_enabled !== false,
          summary_threshold_kb: data.summary_threshold_kb ?? 500,
          summary_max_file_size_mb: data.summary_max_file_size_mb ?? 10,
          read_file_max_lines: data.read_file_max_lines ?? 2000,
          summary_chat_model: data.summary_chat_model || 'gemini-2.5-flash',
        });
      }
    } catch (e) {
      console.error('Failed to load file settings:', e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      const res = await fetch('/admin/api/settings/files', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (res.ok) {
        const updated = await res.json();
        setSettings(updated);
        toast.success('File and summarization settings updated successfully');
      } else {
        const err = await res.json();
        toast.error(err.error || 'Failed to save settings');
      }
    } catch (e: any) {
      toast.error(`Save failed: ${e.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="settings-section glass-card" aria-labelledby="file-settings-heading">
      <div className="section-header">
        <div className="header-icon">
          <i className="fa-solid fa-file-lines"></i>
        </div>
        <div>
          <h2 id="file-settings-heading" style={{ fontSize: '1.1rem', fontWeight: 600 }}>
            Files & Large File Summarization
          </h2>
          <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
            Configure retrieval ceilings for AI agents and automatic LLM summarization thresholds for large files in watched folders and uploads.
          </p>
        </div>
      </div>

      {isLoading ? (
        <div style={{ padding: '24px', textAlign: 'center' }} className="text-muted">
          <i className="fa-solid fa-spinner fa-spin" style={{ marginRight: '8px' }}></i> Loading settings...
        </div>
      ) : (
        <form onSubmit={handleSave} style={{ marginTop: '16px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Auto-Summarization Toggle */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: 'rgba(255,255,255,0.03)', borderRadius: '8px' }}>
              <div>
                <label htmlFor="summary-enabled-toggle" style={{ fontWeight: 600, display: 'block', cursor: 'pointer' }}>
                  Enable Large File Summarization
                </label>
                <span className="text-muted" style={{ fontSize: '0.8rem' }}>
                  Automatically generate and vector-embed an executive summary when files exceed the size threshold instead of skipping them.
                </span>
              </div>
              <input
                id="summary-enabled-toggle"
                type="checkbox"
                checked={settings.summary_enabled}
                onChange={(e) => setSettings({ ...settings, summary_enabled: e.target.checked })}
                style={{ width: '18px', height: '18px', cursor: 'pointer' }}
                aria-label="Enable Large File Summarization"
              />
            </div>

            {/* Threshold Settings Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
              <div>
                <label htmlFor="summary-threshold-input" style={{ fontSize: '0.85rem', fontWeight: 500, display: 'block', marginBottom: '6px' }}>
                  Auto-Summarize Threshold (KB)
                </label>
                <input
                  id="summary-threshold-input"
                  type="number"
                  min="10"
                  max="50000"
                  value={settings.summary_threshold_kb}
                  onChange={(e) => setSettings({ ...settings, summary_threshold_kb: Number(e.target.value) })}
                  className="input-field"
                  style={{ width: '100%' }}
                  disabled={!settings.summary_enabled}
                />
                <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px', display: 'block' }}>
                  Files larger than this (default: 500 KB) trigger LLM summarization.
                </span>
              </div>

              <div>
                <label htmlFor="summary-max-size-input" style={{ fontSize: '0.85rem', fontWeight: 500, display: 'block', marginBottom: '6px' }}>
                  Max File Size for Summarization (MB)
                </label>
                <input
                  id="summary-max-size-input"
                  type="number"
                  min="1"
                  max="100"
                  value={settings.summary_max_file_size_mb}
                  onChange={(e) => setSettings({ ...settings, summary_max_file_size_mb: Number(e.target.value) })}
                  className="input-field"
                  style={{ width: '100%' }}
                  disabled={!settings.summary_enabled}
                />
                <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px', display: 'block' }}>
                  Files larger than this ceiling (default: 10 MB) are skipped to protect memory.
                </span>
              </div>

              <div>
                <label htmlFor="read-file-max-lines-input" style={{ fontSize: '0.85rem', fontWeight: 500, display: 'block', marginBottom: '6px' }}>
                  Max Lines Per Read
                </label>
                <input
                  id="read-file-max-lines-input"
                  type="number"
                  min="50"
                  max="20000"
                  value={settings.read_file_max_lines}
                  onChange={(e) => setSettings({ ...settings, read_file_max_lines: Number(e.target.value) })}
                  className="input-field"
                  style={{ width: '100%' }}
                />
                <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px', display: 'block' }}>
                  Default line ceiling for <code>read_file</code> tool calls (default: 2000 lines).
                </span>
              </div>
            </div>

            {/* Summarization Chat Model */}
            <div>
              <label htmlFor="summary-chat-model-input" style={{ fontSize: '0.85rem', fontWeight: 500, display: 'block', marginBottom: '6px' }}>
                Summarization Chat Model
              </label>
              <input
                id="summary-chat-model-input"
                type="text"
                value={settings.summary_chat_model}
                onChange={(e) => setSettings({ ...settings, summary_chat_model: e.target.value })}
                placeholder="e.g. gemini-2.5-flash or gpt-4o-mini"
                className="input-field"
                style={{ width: '100%' }}
                disabled={!settings.summary_enabled}
              />
              <span className="text-muted" style={{ fontSize: '0.75rem', marginTop: '4px', display: 'block' }}>
                LiteLLM chat model identifier used for generating file summaries.
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
              <button
                type="submit"
                disabled={isSaving}
                className="btn btn-primary"
                style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
              >
                {isSaving ? (
                  <>
                    <i className="fa-solid fa-spinner fa-spin"></i> Saving...
                  </>
                ) : (
                  <>
                    <i className="fa-solid fa-floppy-disk"></i> Save File Settings
                  </>
                )}
              </button>
            </div>
          </div>
        </form>
      )}
    </section>
  );
}
