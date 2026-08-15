import { render, screen } from '@testing-library/react';
import App from '../App';
import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('App', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({})
    } as Response);
  });

  it('renders without crashing', () => {
    render(<App />);
    expect(document.body).toBeInTheDocument();
  });
});
