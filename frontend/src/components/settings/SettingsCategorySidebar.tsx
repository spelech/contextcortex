export type SettingsCategory =
  | 'ai-gateway'
  | 'vector-store'
  | 'embedding'
  | 'auto-sync'
  | 'git-hosts'
  | 'files'
  | 'appearance';

interface SettingsCategorySidebarProps {
  activeCategory: SettingsCategory | 'all';
  onSelectCategory: (category: SettingsCategory) => void;
}

const CATEGORIES: Array<{ id: SettingsCategory; icon: string; label: string }> = [
  { id: 'ai-gateway', icon: 'fa-robot', label: 'AI & Model Gateway' },
  { id: 'vector-store', icon: 'fa-database', label: 'Vector Database' },
  { id: 'embedding', icon: 'fa-microchip', label: 'Embedding Engine' },
  { id: 'auto-sync', icon: 'fa-arrows-rotate', label: 'Auto-Sync & Webhooks' },
  { id: 'git-hosts', icon: 'fa-key', label: 'Git & Host Credentials' },
  { id: 'files', icon: 'fa-file-lines', label: 'File & Summaries' },
  { id: 'appearance', icon: 'fa-palette', label: 'Appearance & Theme' },
];

export function SettingsCategorySidebar({
  activeCategory,
  onSelectCategory,
}: SettingsCategorySidebarProps) {
  return (
    <aside className="settings-category-sidebar" role="tablist" aria-label="Settings Categories">
      {CATEGORIES.map((cat) => (
        <button
          key={cat.id}
          type="button"
          className={`settings-category-btn ${activeCategory === cat.id ? 'active' : ''}`}
          onClick={() => onSelectCategory(cat.id)}
          role="tab"
          aria-selected={activeCategory === cat.id}
        >
          <i className={`fa-solid ${cat.icon}`}></i>
          <span>{cat.label}</span>
        </button>
      ))}
    </aside>
  );
}
