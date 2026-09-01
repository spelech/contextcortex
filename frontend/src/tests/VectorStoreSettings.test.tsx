import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { VectorStoreSettings } from '../components/settings/VectorStoreSettings';
import type { VectorStoreConfig } from '../types';

describe('VectorStoreSettings Component', () => {
  const defaultProps = {
    vectorStore: {
      provider: 'qdrant' as const,
      mode: 'embedded' as const,
      storage_path: 'data/qdrant_db',
      url: null,
      collection: 'knowledge_rag_v1',
      healthy: true,
      points_count: 1450,
    } as VectorStoreConfig,
    isLoadingVs: false,
    testFeedback: null,
    vsProvider: 'qdrant' as const,
    vsMode: 'embedded' as const,
    vsStoragePath: 'data/qdrant_db',
    setVsStoragePath: vi.fn(),
    vsUrl: 'http://localhost:6333',
    setVsUrl: vi.fn(),
    vsCollection: 'knowledge_rag_v1',
    setVsCollection: vi.fn(),
    isTestingVs: false,
    isSwitchingVs: false,
    onProviderChange: vi.fn(),
    onModeChange: vi.fn(),
    onTestConnection: vi.fn(),
    onSwitchBackend: vi.fn(),
  };

  it('renders loading placeholder when isLoadingVs is true and vectorStore is null', () => {
    render(
      <VectorStoreSettings
        {...defaultProps}
        vectorStore={null}
        isLoadingVs={true}
      />
    );
    expect(screen.getByText('Loading vector store configuration...')).toBeInTheDocument();
  });

  it('renders fallback when not loading and vectorStore is null', () => {
    render(
      <VectorStoreSettings
        {...defaultProps}
        vectorStore={null}
        isLoadingVs={false}
      />
    );
    expect(screen.getByText('No vector store configuration found.')).toBeInTheDocument();
  });

  it('renders active vector backend specifications correctly for Qdrant Embedded', () => {
    render(<VectorStoreSettings {...defaultProps} />);

    expect(screen.getByText('Vector Database Engine')).toBeInTheDocument();
    expect(screen.getByText('Active Vector Backend')).toBeInTheDocument();
    expect(screen.getByText('Qdrant')).toBeInTheDocument();
    expect(screen.getByText('Embedded Disk')).toBeInTheDocument();
    expect(screen.getByText('data/qdrant_db')).toBeInTheDocument();
    expect(screen.getByText('knowledge_rag_v1')).toBeInTheDocument();
    expect(screen.getByText('1,450')).toBeInTheDocument();
    expect(screen.getByText('Healthy')).toBeInTheDocument();
  });

  it('renders active vector backend specifications correctly for Chroma Remote with Unhealthy status', () => {
    const chromaConfig: VectorStoreConfig = {
      provider: 'chroma',
      mode: 'remote',
      storage_path: null,
      url: 'http://chroma:8000',
      collection: 'custom_collection',
      healthy: false,
      health_message: 'Connection refused on port 8000',
      points_count: 0,
    };

    render(
      <VectorStoreSettings
        {...defaultProps}
        vectorStore={chromaConfig}
        vsProvider="chroma"
        vsMode="remote"
      />
    );

    expect(screen.getByText('ChromaDB')).toBeInTheDocument();
    expect(screen.getByText('Remote Server')).toBeInTheDocument();
    expect(screen.getByText('http://chroma:8000')).toBeInTheDocument();
    expect(screen.getByText('custom_collection')).toBeInTheDocument();
    expect(screen.getByText(/Connection refused on port 8000/)).toBeInTheDocument();
  });

  it('handles provider and mode changes', () => {
    render(<VectorStoreSettings {...defaultProps} />);

    const providerSelect = screen.getByLabelText('Vector Store Provider');
    fireEvent.change(providerSelect, { target: { value: 'chroma' } });
    expect(defaultProps.onProviderChange).toHaveBeenCalledWith('chroma');

    const modeSelect = screen.getByLabelText('Operating Mode');
    fireEvent.change(modeSelect, { target: { value: 'remote' } });
    expect(defaultProps.onModeChange).toHaveBeenCalledWith('remote');
  });

  it('handles storage path and collection input updates in embedded mode', () => {
    render(<VectorStoreSettings {...defaultProps} />);

    const pathInput = screen.getByLabelText('Storage Directory Path');
    fireEvent.change(pathInput, { target: { value: 'data/custom_path' } });
    expect(defaultProps.setVsStoragePath).toHaveBeenCalledWith('data/custom_path');

    const collectionInput = screen.getByLabelText('Collection Name');
    fireEvent.change(collectionInput, { target: { value: 'custom_vectors' } });
    expect(defaultProps.setVsCollection).toHaveBeenCalledWith('custom_vectors');
  });

  it('handles remote url input update in remote mode', () => {
    render(
      <VectorStoreSettings
        {...defaultProps}
        vsMode="remote"
      />
    );

    const urlInput = screen.getByLabelText('Remote Server URL');
    fireEvent.change(urlInput, { target: { value: 'http://remote-qdrant:6333' } });
    expect(defaultProps.setVsUrl).toHaveBeenCalledWith('http://remote-qdrant:6333');
  });

  it('renders feedback banners for success and error states', () => {
    const { rerender } = render(
      <VectorStoreSettings
        {...defaultProps}
        testFeedback={{ success: true, message: 'Qdrant connection successful (0.005s)' }}
      />
    );

    expect(screen.getByText('Qdrant connection successful (0.005s)')).toBeInTheDocument();

    rerender(
      <VectorStoreSettings
        {...defaultProps}
        testFeedback={{ success: false, message: 'Failed to connect to host' }}
      />
    );

    expect(screen.getByText('Failed to connect to host')).toBeInTheDocument();
  });

  it('triggers test connection and switch backend actions', () => {
    render(<VectorStoreSettings {...defaultProps} />);

    const testBtn = screen.getByRole('button', { name: /Test Connection/i });
    fireEvent.click(testBtn);
    expect(defaultProps.onTestConnection).toHaveBeenCalled();

    const switchBtn = screen.getByRole('button', { name: /Save & Switch Backend/i });
    fireEvent.click(switchBtn);
    expect(defaultProps.onSwitchBackend).toHaveBeenCalled();
  });

  it('disables buttons and shows spinner during testing or switching', () => {
    const { rerender } = render(
      <VectorStoreSettings
        {...defaultProps}
        isTestingVs={true}
      />
    );

    expect(screen.getByRole('button', { name: /Testing Connection\.\.\./i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Save & Switch Backend/i })).toBeDisabled();

    rerender(
      <VectorStoreSettings
        {...defaultProps}
        isSwitchingVs={true}
      />
    );

    expect(screen.getByRole('button', { name: /Test Connection/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Switching Backend\.\.\./i })).toBeDisabled();
  });
});
