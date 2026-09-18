/**
 * Interactive Mermaid Diagram Pan & Zoom Controller with Fullscreen Lightbox
 * ContextCortex VitePress Documentation Enhancement
 */

interface PanZoomState {
  scale: number;
  x: number;
  y: number;
  isDragging: boolean;
  startX: number;
  startY: number;
  initialX: number;
  initialY: number;
}

const MIN_SCALE = 0.2;
const MAX_SCALE = 8.0;
const SCALE_STEP = 1.25;

function createSvgIcon(pathData: string, viewBox = '0 0 24 24'): SVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', viewBox);
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');

  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', pathData);
  svg.appendChild(path);
  return svg;
}

const ICONS = {
  zoomIn: 'M12 5v14M5 12h14',
  zoomOut: 'M5 12h14',
  reset: 'M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8 M3 3v5h5',
  fullscreen: 'M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3',
  close: 'M18 6L6 18M6 6l12 12'
};

function setupPanZoom(
  viewport: HTMLElement,
  target: HTMLElement,
  scaleBadge: HTMLElement | null,
  isDirectWheel = false
): {
  zoomIn: () => void;
  zoomOut: () => void;
  reset: () => void;
  getState: () => PanZoomState;
} {
  const state: PanZoomState = {
    scale: 1,
    x: 0,
    y: 0,
    isDragging: false,
    startX: 0,
    startY: 0,
    initialX: 0,
    initialY: 0
  };

  const applyTransform = () => {
    target.style.transform = `translate(${state.x}px, ${state.y}px) scale(${state.scale})`;
    if (scaleBadge) {
      scaleBadge.textContent = `${Math.round(state.scale * 100)}%`;
    }
  };

  const updateZoomAtPoint = (newScale: number, clientX: number, clientY: number) => {
    const clampedScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, newScale));
    if (clampedScale === state.scale) return;

    const rect = viewport.getBoundingClientRect();
    const mouseX = clientX - rect.left;
    const mouseY = clientY - rect.top;

    const diagX = (mouseX - state.x) / state.scale;
    const diagY = (mouseY - state.y) / state.scale;

    state.x = mouseX - diagX * clampedScale;
    state.y = mouseY - diagY * clampedScale;
    state.scale = clampedScale;

    applyTransform();
  };

  const zoomIn = () => {
    const rect = viewport.getBoundingClientRect();
    updateZoomAtPoint(state.scale * SCALE_STEP, rect.left + rect.width / 2, rect.top + rect.height / 2);
  };

  const zoomOut = () => {
    const rect = viewport.getBoundingClientRect();
    updateZoomAtPoint(state.scale / SCALE_STEP, rect.left + rect.width / 2, rect.top + rect.height / 2);
  };

  const reset = () => {
    state.scale = 1;
    state.x = 0;
    state.y = 0;
    applyTransform();
  };

  // Pointer Drag to Pan
  viewport.addEventListener('pointerdown', (e: PointerEvent) => {
    if (e.button !== 0) return; // Primary button only
    state.isDragging = true;
    state.startX = e.clientX;
    state.startY = e.clientY;
    state.initialX = state.x;
    state.initialY = state.y;
    viewport.classList.add('is-dragging');
    viewport.setPointerCapture(e.pointerId);
  });

  viewport.addEventListener('pointermove', (e: PointerEvent) => {
    if (!state.isDragging) return;
    state.x = state.initialX + (e.clientX - state.startX);
    state.y = state.initialY + (e.clientY - state.startY);
    applyTransform();
  });

  const onPointerUp = (e: PointerEvent) => {
    if (state.isDragging) {
      state.isDragging = false;
      viewport.classList.remove('is-dragging');
      try {
        viewport.releasePointerCapture(e.pointerId);
      } catch {}
    }
  };

  viewport.addEventListener('pointerup', onPointerUp);
  viewport.addEventListener('pointercancel', onPointerUp);

  // Wheel to Zoom
  viewport.addEventListener('wheel', (e: WheelEvent) => {
    if (isDirectWheel || e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
      updateZoomAtPoint(state.scale * zoomFactor, e.clientX, e.clientY);
    }
  }, { passive: false });

  // Double click to reset
  viewport.addEventListener('dblclick', (e: MouseEvent) => {
    if (state.scale !== 1 || state.x !== 0 || state.y !== 0) {
      reset();
    } else {
      updateZoomAtPoint(1.75, e.clientX, e.clientY);
    }
  });

  applyTransform();

  return { zoomIn, zoomOut, reset, getState: () => state };
}

function openFullscreenModal(sourceSvg: SVGElement) {
  const modal = document.createElement('div');
  modal.className = 'mermaid-fullscreen-modal';

  const header = document.createElement('div');
  header.className = 'mermaid-modal-header';

  const title = document.createElement('div');
  title.className = 'mermaid-modal-title';
  title.innerHTML = '<i class="fa-solid fa-diagram-project"></i> Mermaid Diagram Explorer';

  const actions = document.createElement('div');
  actions.className = 'mermaid-modal-actions';

  const scaleBadge = document.createElement('span');
  scaleBadge.className = 'mermaid-scale-badge';
  scaleBadge.textContent = '100%';

  const zoomInBtn = document.createElement('button');
  zoomInBtn.className = 'mermaid-toolbar-btn';
  zoomInBtn.title = 'Zoom In';
  zoomInBtn.appendChild(createSvgIcon(ICONS.zoomIn));

  const zoomOutBtn = document.createElement('button');
  zoomOutBtn.className = 'mermaid-toolbar-btn';
  zoomOutBtn.title = 'Zoom Out';
  zoomOutBtn.appendChild(createSvgIcon(ICONS.zoomOut));

  const resetBtn = document.createElement('button');
  resetBtn.className = 'mermaid-toolbar-btn';
  resetBtn.title = 'Reset Zoom';
  resetBtn.appendChild(createSvgIcon(ICONS.reset));

  const closeBtn = document.createElement('button');
  closeBtn.className = 'mermaid-toolbar-btn';
  closeBtn.title = 'Close Fullscreen (Esc)';
  closeBtn.appendChild(createSvgIcon(ICONS.close));

  actions.appendChild(scaleBadge);
  actions.appendChild(zoomInBtn);
  actions.appendChild(zoomOutBtn);
  actions.appendChild(resetBtn);
  actions.appendChild(closeBtn);

  header.appendChild(title);
  header.appendChild(actions);

  const viewport = document.createElement('div');
  viewport.className = 'mermaid-modal-viewport';

  const target = document.createElement('div');
  target.className = 'mermaid-modal-target';

  const clonedSvg = sourceSvg.cloneNode(true) as SVGElement;
  target.appendChild(clonedSvg);
  viewport.appendChild(target);

  modal.appendChild(header);
  modal.appendChild(viewport);
  document.body.appendChild(modal);
  document.body.style.overflow = 'hidden';

  const controller = setupPanZoom(viewport, target, scaleBadge, true);

  zoomInBtn.addEventListener('click', controller.zoomIn);
  zoomOutBtn.addEventListener('click', controller.zoomOut);
  resetBtn.addEventListener('click', controller.reset);

  const closeModal = () => {
    document.removeEventListener('keydown', onKeyDown);
    document.body.style.overflow = '';
    modal.remove();
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      closeModal();
    } else if (e.key === '+' || e.key === '=') {
      controller.zoomIn();
    } else if (e.key === '-' || e.key === '_') {
      controller.zoomOut();
    } else if (e.key === '0') {
      controller.reset();
    }
  };

  closeBtn.addEventListener('click', closeModal);
  document.addEventListener('keydown', onKeyDown);
}

export function enhanceMermaidDiagram(mermaidEl: HTMLElement) {
  if (mermaidEl.dataset.panzoomInitialized === 'true') return;

  const svg = mermaidEl.querySelector('svg');
  if (!svg) {
    // Wait for Mermaid.vue to asynchronously render SVG into v-html
    const observer = new MutationObserver((_, obs) => {
      const lateSvg = mermaidEl.querySelector('svg');
      if (lateSvg) {
        obs.disconnect();
        enhanceMermaidDiagram(mermaidEl);
      }
    });
    observer.observe(mermaidEl, { childList: true, subtree: true });
    return;
  }

  mermaidEl.dataset.panzoomInitialized = 'true';

  // Check if already wrapped
  if (mermaidEl.parentElement?.classList.contains('mermaid-panzoom-target')) return;

  const wrapper = document.createElement('div');
  wrapper.className = 'mermaid-panzoom-wrapper';

  const viewport = document.createElement('div');
  viewport.className = 'mermaid-panzoom-viewport';

  const target = document.createElement('div');
  target.className = 'mermaid-panzoom-target';

  // Build Toolbar
  const toolbar = document.createElement('div');
  toolbar.className = 'mermaid-panzoom-toolbar';

  const scaleBadge = document.createElement('span');
  scaleBadge.className = 'mermaid-scale-badge';
  scaleBadge.textContent = '100%';

  const zoomInBtn = document.createElement('button');
  zoomInBtn.className = 'mermaid-toolbar-btn';
  zoomInBtn.title = 'Zoom In';
  zoomInBtn.setAttribute('aria-label', 'Zoom In');
  zoomInBtn.appendChild(createSvgIcon(ICONS.zoomIn));

  const zoomOutBtn = document.createElement('button');
  zoomOutBtn.className = 'mermaid-toolbar-btn';
  zoomOutBtn.title = 'Zoom Out';
  zoomOutBtn.setAttribute('aria-label', 'Zoom Out');
  zoomOutBtn.appendChild(createSvgIcon(ICONS.zoomOut));

  const resetBtn = document.createElement('button');
  resetBtn.className = 'mermaid-toolbar-btn';
  resetBtn.title = 'Reset Zoom';
  resetBtn.setAttribute('aria-label', 'Reset Zoom');
  resetBtn.appendChild(createSvgIcon(ICONS.reset));

  const fullscreenBtn = document.createElement('button');
  fullscreenBtn.className = 'mermaid-toolbar-btn';
  fullscreenBtn.title = 'Fullscreen Explorer';
  fullscreenBtn.setAttribute('aria-label', 'Fullscreen Explorer');
  fullscreenBtn.appendChild(createSvgIcon(ICONS.fullscreen));

  toolbar.appendChild(scaleBadge);
  toolbar.appendChild(zoomInBtn);
  toolbar.appendChild(zoomOutBtn);
  toolbar.appendChild(resetBtn);
  toolbar.appendChild(fullscreenBtn);

  const hint = document.createElement('div');
  hint.className = 'mermaid-panzoom-hint';
  hint.textContent = 'Drag to pan • Ctrl + scroll to zoom • Double-click to reset';

  // Wrap mermaidEl in target -> viewport -> wrapper
  const parent = mermaidEl.parentNode;
  if (!parent) return;

  parent.insertBefore(wrapper, mermaidEl);
  target.appendChild(mermaidEl);
  viewport.appendChild(target);
  wrapper.appendChild(toolbar);
  wrapper.appendChild(viewport);
  wrapper.appendChild(hint);

  const controller = setupPanZoom(viewport, target, scaleBadge, false);

  zoomInBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    controller.zoomIn();
  });

  zoomOutBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    controller.zoomOut();
  });

  resetBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    controller.reset();
  });

  fullscreenBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const currentSvg = target.querySelector('svg');
    if (currentSvg) {
      openFullscreenModal(currentSvg);
    }
  });
}

export function initMermaidPanZoom() {
  if (typeof window === 'undefined') return;

  const elements = document.querySelectorAll<HTMLElement>('.mermaid:not([data-panzoom-initialized="true"])');
  elements.forEach((el) => {
    enhanceMermaidDiagram(el);
  });
}

let globalObserver: MutationObserver | null = null;

export function setupMermaidObserver() {
  if (typeof window === 'undefined') return;

  initMermaidPanZoom();

  if (!globalObserver) {
    globalObserver = new MutationObserver((mutations) => {
      let shouldCheck = false;
      for (const m of mutations) {
        if (m.addedNodes.length > 0) {
          shouldCheck = true;
          break;
        }
      }
      if (shouldCheck) {
        initMermaidPanZoom();
      }
    });

    globalObserver.observe(document.body, {
      childList: true,
      subtree: true
    });
  }
}
