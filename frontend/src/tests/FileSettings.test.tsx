import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { FileSettings } from '../components/settings/FileSettings';
import { ToastProvider } from '../ToastContext';

describe('FileSettings Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders settings fields and loads data from api', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(((url: any) => {
      if (url === '/admin/api/settings/files') {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              summary_enabled: true,
              summary_threshold_kb: 500,
              summary_max_file_size_mb: 10,
              read_file_max_lines: 2000,
              summary_chat_model: 'gemini-2.5-flash',
            }),
        } as Response);
      }
      return Promise.reject(new Error('Unknown url'));
    }) as any);

    render(
      <ToastProvider>
        <FileSettings />
      </ToastProvider>
    );

    expect(screen.getByText(/Loading settings.../i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Files & Large File Summarization')).toBeInTheDocument();
    });

    const toggle = screen.getByLabelText(/Enable Large File Summarization/i);
    expect(toggle).toBeChecked();

    const thresholdInput = screen.getByLabelText(/Auto-Summarize Threshold/i);
    expect(thresholdInput).toHaveValue(500);

    const maxLinesInput = screen.getByLabelText(/Max Lines Per Read/i);
    expect(maxLinesInput).toHaveValue(2000);
  });

  it('submits updated settings when Save button is clicked', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(((url: any, opts?: any) => {
      if (url === '/admin/api/settings/files' && (!opts || opts.method === undefined)) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              summary_enabled: true,
              summary_threshold_kb: 500,
              summary_max_file_size_mb: 10,
              read_file_max_lines: 2000,
              summary_chat_model: 'gemini-2.5-flash',
            }),
        } as Response);
      }
      if (url === '/admin/api/settings/files' && opts?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(JSON.parse(opts.body as string)),
        } as Response);
      }
      return Promise.reject(new Error('Unknown url'));
    }) as any);

    render(
      <ToastProvider>
        <FileSettings />
      </ToastProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Files & Large File Summarization')).toBeInTheDocument();
    });

    const thresholdInput = screen.getByLabelText(/Auto-Summarize Threshold/i);
    fireEvent.change(thresholdInput, { target: { value: '750' } });

    const saveBtn = screen.getByRole('button', { name: /Save File Settings/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        '/admin/api/settings/files',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"summary_threshold_kb":750'),
        })
      );
    });
  });
});
