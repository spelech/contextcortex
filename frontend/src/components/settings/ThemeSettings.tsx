import { useState, useEffect } from 'react';
import { AVAILABLE_THEMES, getSavedTheme, applyTheme, type ThemeId } from '../../theme';
import { useToast } from '../../ToastContext';

export function ThemeSettings() {
  const [currentTheme, setCurrentTheme] = useState<ThemeId>('deep-ocean');
  const toast = useToast();

  useEffect(() => {
    setCurrentTheme(getSavedTheme());
  }, []);

  const handleSelectTheme = (themeId: ThemeId, themeName: string) => {
    applyTheme(themeId);
    setCurrentTheme(themeId);
    toast.success(`Switched theme to ${themeName}`);
  };

  return (
    <section className="settings-section glass-card" aria-labelledby="theme-settings-heading">
      <div className="section-header">
        <div className="header-icon">
          <i className="fa-solid fa-palette"></i>
        </div>
        <div>
          <h2 id="theme-settings-heading" style={{ fontSize: '1.1rem', fontWeight: 600 }}>Appearance & Theme</h2>
          <p className="text-muted" style={{ marginTop: '4px', fontSize: '0.85rem' }}>
            Choose your preferred color scheme. The selected theme will persist across browser sessions.
          </p>
        </div>
      </div>

      <div className="theme-options-grid" role="radiogroup" aria-label="Appearance Themes">
        {AVAILABLE_THEMES.map((theme) => {
          const isActive = currentTheme === theme.id;
          return (
            <button
              key={theme.id}
              type="button"
              className={`theme-card ${isActive ? 'active' : ''}`}
              onClick={() => handleSelectTheme(theme.id, theme.name)}
              role="radio"
              aria-checked={isActive}
              aria-label={`Select ${theme.name} theme`}
            >
              <div className="theme-card-header">
                <div className="theme-card-title">
                  <span>{theme.name}</span>
                  <span className="badge" style={{ fontSize: '0.68rem', fontWeight: 500, opacity: 0.85, padding: '2px 6px' }}>
                    <i className={`fa-solid ${theme.mode === 'dark' ? 'fa-moon' : 'fa-sun'}`} style={{ marginRight: '3px' }}></i>
                    {theme.mode === 'dark' ? 'Dark' : 'Light'}
                  </span>
                </div>
                {isActive ? (
                  <span className="badge badge-accent">
                    <i className="fa-solid fa-check" style={{ marginRight: '4px' }}></i> Active
                  </span>
                ) : (
                  <span className="badge badge-primary">Select</span>
                )}
              </div>

              <div className="theme-card-desc">
                {theme.description}
              </div>

              <div className="theme-swatches" aria-hidden="true">
                {theme.swatches.map((color, idx) => (
                  <span
                    key={idx}
                    className="theme-swatch"
                    style={{ backgroundColor: color }}
                    title={color}
                  />
                ))}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
