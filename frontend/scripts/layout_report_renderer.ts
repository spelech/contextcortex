import type { Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

export interface ViewportConfig {
  name: string;
  width: number;
  height: number;
  deviceScaleFactor: number;
}

export interface AuditTabSpec {
  id: string;
  name: string;
}

export interface EvaluatedElementBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface EvaluatedElementRecord {
  selector: string;
  tag: string;
  text: string;
  box: EvaluatedElementBox;
  scrollWidth: number;
  clientWidth: number;
  status: 'clean' | 'overflow' | 'clipping' | 'collision';
  violationType?: string;
  overflowPixels?: number;
  details?: string;
}

export interface PageLayoutEvaluation {
  elements: EvaluatedElementRecord[];
  violations: EvaluatedElementRecord[];
}

export interface TabAuditReport {
  tab: string;
  tabName: string;
  screenshot: string;
  elementsCount: number;
  violationsCount: number;
  violations: EvaluatedElementRecord[];
  elements: EvaluatedElementRecord[];
}

export interface ViewportAuditReport {
  name: string;
  width: number;
  height: number;
  deviceScaleFactor: number;
  tabs: TabAuditReport[];
}

export interface LayoutAuditSummary {
  totalViewports: number;
  totalTabs: number;
  totalEvaluations: number;
  totalViolations: number;
  overflowViolations: number;
  clippingViolations: number;
  collisionViolations: number;
  passed: boolean;
}

export interface LayoutAuditReport {
  timestamp: string;
  summary: LayoutAuditSummary;
  viewports: ViewportAuditReport[];
}

export async function ensureDirectoryExists(dirPath: string): Promise<void> {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
}

export async function evaluatePageLayout(
  page: Page,
  viewportWidth: number,
  viewportHeight: number
): Promise<PageLayoutEvaluation> {
  return await page.evaluate(
    (args: { viewportWidth: number; viewportHeight: number }) => {
      const { viewportWidth: vpWidth } = args;

      function getElementSelector(el: Element): string {
        if (el.id) return `#${el.id}`;
        const tag = el.tagName.toLowerCase();
        const classes = Array.from(el.classList)
          .filter((c) => !c.startsWith('ng-') && !c.includes(':') && c.length < 30)
          .slice(0, 3);
        const classStr = classes.length > 0 ? `.${classes.join('.')}` : '';

        let parentDesc = '';
        if (
          el.parentElement &&
          el.parentElement !== document.body &&
          el.parentElement !== document.documentElement
        ) {
          const parentTag = el.parentElement.tagName.toLowerCase();
          const parentFirstClass =
            el.parentElement.classList.length > 0 ? `.${el.parentElement.classList[0]}` : '';
          parentDesc = `${parentTag}${parentFirstClass} > `;
        }
        return `${parentDesc}${tag}${classStr}`;
      }

      const elementsToCheck: Array<{
        el: HTMLElement;
        selector: string;
        tag: string;
        text: string;
        rect: DOMRect;
      }> = [];

      const candidates = document.querySelectorAll(
        'header, nav, main, section, div.card, div.repo-card, div.path-card, div.metric-card, div.stat-card, div.system-spec-card, ' +
          'button, input, select, textarea, form, .form-group, .form-row, .btn, .badge, ' +
          'table, tr, th, td, .log-item, .search-result-item, .header-status, .status-item, h1, h2, h3, p'
      );

      const seenElements = new Set<Element>();

      candidates.forEach((node) => {
        const el = node as HTMLElement;
        if (!el || seenElements.has(el)) return;
        seenElements.add(el);

        if (el.classList.contains('background-decor') || el.classList.contains('circle')) return;

        const style = window.getComputedStyle(el);
        if (
          style.display === 'none' ||
          style.visibility === 'hidden' ||
          parseFloat(style.opacity || '1') === 0
        ) {
          return;
        }

        const navParent = el.closest('.dashboard-nav');
        if (navParent && !navParent.classList.contains('drawer-open') && window.innerWidth < 768) {
          return;
        }

        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return;

        elementsToCheck.push({
          el,
          selector: getElementSelector(el),
          tag: el.tagName,
          text: (el.innerText || el.textContent || '').trim().slice(0, 40),
          rect,
        });
      });

      const evaluatedElements: EvaluatedElementRecord[] = [];
      const violations: EvaluatedElementRecord[] = [];

      for (let i = 0; i < elementsToCheck.length; i++) {
        const item = elementsToCheck[i];
        const { el, selector, tag, text, rect } = item;
        const style = window.getComputedStyle(el);

        let status: 'clean' | 'overflow' | 'clipping' | 'collision' = 'clean';
        let violationType: string | undefined = undefined;
        let details: string | undefined = undefined;
        let overflowPixels = 0;

        const scrollParent = el.closest(
          '.table-container, .table-responsive, .settings-category-sidebar, .nav-toolbar, .dashboard-nav, .log-filter-pills, [style*="overflow-x: auto"], [style*="overflow-x: scroll"], pre, .traceback-container, .traceback-box'
        );
        const isInsideScrollContainer = scrollParent && scrollParent !== el;

        const rightOverflow = rect.right - vpWidth;
        const leftOverflow = -rect.left;

        if (!isInsideScrollContainer) {
          if (rightOverflow > 0.5) {
            status = 'overflow';
            violationType = 'VIEWPORT_OVERFLOW';
            overflowPixels = Math.round(rightOverflow * 10) / 10;
            details = `Element overflows viewport right edge by ${overflowPixels}px (rect.right: ${rect.right.toFixed(1)}px, viewport: ${vpWidth}px)`;
          } else if (leftOverflow > 0.5 && !style.position?.includes('fixed')) {
            status = 'overflow';
            violationType = 'VIEWPORT_OVERFLOW';
            overflowPixels = Math.round(leftOverflow * 10) / 10;
            details = `Element overflows viewport left edge by ${overflowPixels}px (rect.left: ${rect.left.toFixed(1)}px)`;
          }
        }

        if (status === 'clean' && el.scrollWidth > el.clientWidth + 1.5) {
          const isDesignatedScroll =
            style.overflowX === 'auto' ||
            style.overflowX === 'scroll' ||
            style.overflow === 'hidden' ||
            style.textOverflow === 'ellipsis' ||
            el.classList.contains('table-container') ||
            el.classList.contains('table-responsive') ||
            el.classList.contains('traceback-container') ||
            el.classList.contains('traceback-box') ||
            tag === 'PRE' ||
            tag === 'CODE' ||
            tag === 'INPUT' ||
            tag === 'TEXTAREA' ||
            tag === 'SELECT';

          if (!isDesignatedScroll) {
            status = 'clipping';
            violationType = 'CONTAINER_CLIPPING';
            overflowPixels = el.scrollWidth - el.clientWidth;
            details = `Container content (${el.scrollWidth}px) exceeds client width (${el.clientWidth}px) without intentional scroll wrapper`;
          }
        }

        if (status === 'clean') {
          for (let j = i + 1; j < elementsToCheck.length; j++) {
            const other = elementsToCheck[j];
            if (el.contains(other.el) || other.el.contains(el)) continue;
            if (el.parentElement !== other.el.parentElement) continue;

            const oRect = other.rect;
            const xOverlap = Math.min(rect.right, oRect.right) - Math.max(rect.left, oRect.left);
            const yOverlap = Math.min(rect.bottom, oRect.bottom) - Math.max(rect.top, oRect.top);

            if (xOverlap > 4 && yOverlap > 4) {
              const oStyle = window.getComputedStyle(other.el);
              if (
                style.position === 'absolute' ||
                oStyle.position === 'absolute' ||
                style.position === 'fixed' ||
                oStyle.position === 'fixed'
              ) {
                continue;
              }
              status = 'collision';
              violationType = 'ELEMENT_COLLISION';
              details = `Element collides with sibling ${other.selector} (overlap area: ${Math.round(xOverlap)}x${Math.round(yOverlap)}px)`;
              break;
            }
          }
        }

        const elementRecord: EvaluatedElementRecord = {
          selector,
          tag,
          text,
          box: {
            x: Math.round(rect.x * 10) / 10,
            y: Math.round(rect.y * 10) / 10,
            width: Math.round(rect.width * 10) / 10,
            height: Math.round(rect.height * 10) / 10,
          },
          scrollWidth: el.scrollWidth,
          clientWidth: el.clientWidth,
          status,
          violationType,
          overflowPixels: overflowPixels > 0 ? overflowPixels : undefined,
          details,
        };

        evaluatedElements.push(elementRecord);
        if (status !== 'clean') {
          violations.push(elementRecord);
        }
      }

      return {
        elements: evaluatedElements,
        violations,
      };
    },
    { viewportWidth, viewportHeight }
  );
}

export function createInitialAuditReport(
  totalViewports: number,
  totalTabs: number
): LayoutAuditReport {
  return {
    timestamp: new Date().toISOString(),
    summary: {
      totalViewports,
      totalTabs,
      totalEvaluations: totalViewports * totalTabs,
      totalViolations: 0,
      overflowViolations: 0,
      clippingViolations: 0,
      collisionViolations: 0,
      passed: true,
    },
    viewports: [],
  };
}

export function recordTabAuditEvaluation(
  auditResults: LayoutAuditReport,
  vpReport: ViewportAuditReport,
  tab: AuditTabSpec,
  relativeScreenshotPath: string,
  evaluation: PageLayoutEvaluation
): void {
  const tabReport: TabAuditReport = {
    tab: tab.id,
    tabName: tab.name,
    screenshot: relativeScreenshotPath,
    elementsCount: evaluation.elements.length,
    violationsCount: evaluation.violations.length,
    violations: evaluation.violations,
    elements: evaluation.elements,
  };

  vpReport.tabs.push(tabReport);

  auditResults.summary.totalViolations += evaluation.violations.length;
  evaluation.violations.forEach((v) => {
    if (v.violationType === 'VIEWPORT_OVERFLOW') auditResults.summary.overflowViolations++;
    else if (v.violationType === 'CONTAINER_CLIPPING') auditResults.summary.clippingViolations++;
    else if (v.violationType === 'ELEMENT_COLLISION') auditResults.summary.collisionViolations++;
  });

  if (evaluation.violations.length === 0) {
    console.log(`[PASS: 0 violations, ${evaluation.elements.length} elements]`);
  } else {
    console.log(`[FAIL: ${evaluation.violations.length} violations]`);
    evaluation.violations.forEach((v) => {
      console.log(`      * [${v.violationType}] ${v.selector}: ${v.details}`);
    });
  }
}

export function writeLayoutAuditReports(
  auditResults: LayoutAuditReport,
  distReportDir: string,
  templatePath: string
): { jsonPath: string; htmlPath: string } {
  auditResults.summary.passed = auditResults.summary.totalViolations === 0;

  const jsonPath = path.join(distReportDir, 'layout-audit.json');
  fs.writeFileSync(jsonPath, JSON.stringify(auditResults, null, 2), 'utf-8');
  console.log(`\n📄 Generated layout audit JSON: ${jsonPath}`);

  if (!fs.existsSync(templatePath)) {
    throw new Error(`Report template not found at ${templatePath}`);
  }
  const templateHtml = fs.readFileSync(templatePath, 'utf-8');

  const compiledHtml = templateHtml.replace(
    '/* __AUDIT_DATA__ */ null',
    JSON.stringify(auditResults, null, 2)
  );

  const htmlPath = path.join(distReportDir, 'index.html');
  fs.writeFileSync(htmlPath, compiledHtml, 'utf-8');
  console.log(`🎨 Generated interactive visual HTML report: ${htmlPath}`);

  console.log('\n====================================================');
  console.log(` Final Audit Status: ${auditResults.summary.passed ? 'PASSED ✅' : 'FAILED ❌'}`);
  console.log(` Total Violations: ${auditResults.summary.totalViolations}`);
  console.log(` Viewport Overflows: ${auditResults.summary.overflowViolations}`);
  console.log(` Container Clippings: ${auditResults.summary.clippingViolations}`);
  console.log(` Element Collisions: ${auditResults.summary.collisionViolations}`);
  console.log('====================================================\n');

  return { jsonPath, htmlPath };
}
