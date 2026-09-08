import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import PdfPreviewModal from '../PdfPreviewModal';
import type { PdfPreviewData } from '../types';

const mockPdfData: PdfPreviewData = {
  filename: 'ASD-STE100.pdf',
  total_pages: 3,
  total_characters: 4500,
  ocr_pages_count: 1,
  pages: [
    {
      page_number: 1,
      text: 'ASD-STE100 Issue 8 Specification Overview',
      char_count: 1500,
      ocr_applied: false
    },
    {
      page_number: 2,
      text: 'Section 2 Scanned Diagram Text via OCR',
      char_count: 1200,
      ocr_applied: true
    },
    {
      page_number: 3,
      text: 'Section 3 Dictionary and Approved Vocabulary',
      char_count: 1800,
      ocr_applied: false
    }
  ],
  sample_chunks: [
    {
      chunk_index: 0,
      page_number: 1,
      heading: 'Page 1',
      char_count: 500,
      preview: 'ASD-STE100 Issue 8 Specification Overview - Part 1'
    },
    {
      chunk_index: 1,
      page_number: 2,
      heading: 'Page 2',
      char_count: 450,
      preview: 'Section 2 Scanned Diagram Text via OCR - Diagram Chunks'
    }
  ]
};

describe('PdfPreviewModal', () => {
  it('renders header, document metrics, and default page text tab', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    render(
      <PdfPreviewModal
        data={mockPdfData}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );

    expect(screen.getByText('PDF Extraction Preview')).toBeInTheDocument();
    expect(screen.getByText('ASD-STE100.pdf')).toBeInTheDocument();
    expect(screen.getByTestId('total-pages-badge')).toHaveTextContent('3');
    expect(screen.getByTestId('total-chars-badge')).toHaveTextContent('4,500');
    expect(screen.getByTestId('ocr-count-badge')).toHaveTextContent('1 page');

    // Page 1 is displayed initially
    expect(screen.getByTestId('page-text-content')).toHaveTextContent('ASD-STE100 Issue 8 Specification Overview');
    expect(screen.getByTestId('page-digital-badge')).toHaveTextContent('Digital');
  });

  it('navigates through pages using Next and Prev buttons', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    render(
      <PdfPreviewModal
        data={mockPdfData}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );

    const prevBtn = screen.getByRole('button', { name: /previous page/i });
    const nextBtn = screen.getByRole('button', { name: /next page/i });

    expect(prevBtn).toBeDisabled();
    expect(nextBtn).toBeEnabled();

    // Click Next -> Page 2 (OCR page)
    fireEvent.click(nextBtn);

    expect(screen.getByTestId('page-text-content')).toHaveTextContent('Section 2 Scanned Diagram Text via OCR');
    expect(screen.getByTestId('page-ocr-applied-badge')).toHaveTextContent('OCR Fallback');
    expect(prevBtn).toBeEnabled();

    // Click Next -> Page 3
    fireEvent.click(nextBtn);
    expect(screen.getByTestId('page-text-content')).toHaveTextContent('Section 3 Dictionary');
    expect(nextBtn).toBeDisabled();

    // Click Prev -> back to Page 2
    fireEvent.click(prevBtn);
    expect(screen.getByTestId('page-text-content')).toHaveTextContent('Section 2 Scanned Diagram Text via OCR');
  });

  it('allows jumping to a specific page via page select dropdown', () => {
    render(
      <PdfPreviewModal
        data={mockPdfData}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    const select = screen.getByLabelText(/select page/i);
    fireEvent.change(select, { target: { value: '2' } }); // Page 3 (index 2)

    expect(screen.getByTestId('page-text-content')).toHaveTextContent('Section 3 Dictionary and Approved Vocabulary');
  });

  it('toggles to sample vector chunks tab and displays chunk cards', () => {
    render(
      <PdfPreviewModal
        data={mockPdfData}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    const chunksTabBtn = screen.getByTestId('tab-chunks-btn');
    fireEvent.click(chunksTabBtn);

    expect(screen.getByTestId('chunks-container')).toBeInTheDocument();
    expect(screen.getByTestId('chunk-card-0')).toBeInTheDocument();
    expect(screen.getByTestId('chunk-card-1')).toBeInTheDocument();
    expect(screen.getByText(/ASD-STE100 Issue 8 Specification Overview - Part 1/)).toBeInTheDocument();
  });

  it('calls onConfirm when clicking Confirm & Ingest to Vector DB', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    render(
      <PdfPreviewModal
        data={mockPdfData}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );

    const confirmBtn = screen.getByTestId('confirm-ingest-btn');
    fireEvent.click(confirmBtn);

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('shows loading state on confirm button when isIngesting is true', () => {
    render(
      <PdfPreviewModal
        data={mockPdfData}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isIngesting={true}
      />
    );

    const confirmBtn = screen.getByTestId('confirm-ingest-btn');
    expect(confirmBtn).toBeDisabled();
    expect(confirmBtn).toHaveTextContent('Ingesting...');
  });

  it('calls onCancel when clicking Cancel or close button', () => {
    const onCancel = vi.fn();

    render(
      <PdfPreviewModal
        data={mockPdfData}
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByLabelText(/close modal/i));
    expect(onCancel).toHaveBeenCalledTimes(2);
  });
});
