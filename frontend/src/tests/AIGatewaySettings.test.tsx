import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AIGatewaySettings } from '../components/settings/AIGatewaySettings';
import { ToastProvider } from '../ToastContext';

const mockConfig = {
  url: 'http://litellm:4000/v1',
  has_api_key: true,
  masked_api_key: 'sk-••••••••••••3a9f',
  chat_model: 'gemini-2.5-flash',
  vision_ocr_model: 'gemini-2.5-flash',
  embedding_model: 'BAAI/bge-small-en-v1.5',
};

const renderWithToast = (ui: React.ReactElement) => {
  return render(<ToastProvider>{ui}</ToastProvider>);
};

describe('AIGatewaySettings Component', () => {
  it('renders masked api key and exposes change key input when clicked', () => {
    renderWithToast(
      <AIGatewaySettings
        config={mockConfig}
        isLoading={false}
        isSaving={false}
        onSave={vi.fn()}
      />
    );

    expect(screen.getByText(/sk-••••••••••••3a9f/i)).toBeInTheDocument();
    const changeBtn = screen.getByRole('button', { name: /change key/i });
    fireEvent.click(changeBtn);

    expect(screen.getByPlaceholderText(/enter api key/i)).toBeInTheDocument();
  });

  it('submits updated settings with new key', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    renderWithToast(
      <AIGatewaySettings
        config={mockConfig}
        isLoading={false}
        isSaving={false}
        onSave={onSave}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /change key/i }));
    const keyInput = screen.getByPlaceholderText(/enter api key/i);
    fireEvent.change(keyInput, { target: { value: 'sk-newsecret1234' } });

    const submitBtn = screen.getByRole('button', { name: /save ai gateway settings/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith(
        expect.objectContaining({
          url: 'http://litellm:4000/v1',
          api_key: 'sk-newsecret1234',
        })
      );
    });
  });

  it('discovers models and populates dropdown selections', async () => {
    const mockDiscover = vi.fn().mockResolvedValue({
      status: 'success',
      total_models: 2,
      chat_models: [{ id: 'gpt-4o' }, { id: 'claude-3-5-sonnet' }],
      vision_models: [{ id: 'gpt-4o' }],
      embedding_models: [{ id: 'text-embedding-3-small' }],
    });

    renderWithToast(
      <AIGatewaySettings
        config={mockConfig}
        isLoading={false}
        isSaving={false}
        onSave={vi.fn()}
        onTestConnection={mockDiscover}
      />
    );

    const testBtn = screen.getByRole('button', { name: /test connection & discover models/i });
    fireEvent.click(testBtn);

    await waitFor(() => {
      expect(mockDiscover).toHaveBeenCalled();
      expect(screen.getByText(/connected successfully/i)).toBeInTheDocument();
      expect(screen.getByRole('option', { name: 'claude-3-5-sonnet' })).toBeInTheDocument();
    });
  });
});
