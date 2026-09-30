import { useState } from 'react';
import LocalPathManager from './LocalPathManager';
import LocalStorageManager from './LocalStorageManager';

interface FilesAndStorageProps {
  refreshStats: () => void;
}

export default function FilesAndStorage({ refreshStats }: FilesAndStorageProps) {
  const [section, setSection] = useState<'local-paths' | 'local-storage'>('local-paths');

  return (
    <div className="files-storage-page">
      <div className="files-storage-header">
        <h2 className="page-title">
          <i className="fa-solid fa-folder-tree" style={{ marginRight: '10px' }}></i>
          Files &amp; Storage
        </h2>
        <div className="files-storage-section-tabs">
          <button
            className={`section-tab ${section === 'local-paths' ? 'active' : ''}`}
            onClick={() => setSection('local-paths')}
          >
            <i className="fa-solid fa-folder-tree"></i>
            <span>Local Paths</span>
          </button>
          <button
            className={`section-tab ${section === 'local-storage' ? 'active' : ''}`}
            onClick={() => setSection('local-storage')}
          >
            <i className="fa-solid fa-hard-drive"></i>
            <span>Local Storage</span>
          </button>
        </div>
      </div>

      <div className="files-storage-content">
        {section === 'local-paths' && (
          <LocalPathManager refreshStats={refreshStats} />
        )}
        {section === 'local-storage' && (
          <LocalStorageManager refreshStats={refreshStats} />
        )}
      </div>
    </div>
  );
}
