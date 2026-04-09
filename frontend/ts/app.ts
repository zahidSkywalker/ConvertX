/**
 * ConvertX Application Shell — Complete Production Version.
 * Orchestrates routing, state, upload, API calls, and UI updates.
 */
import { TOOLS, CATEGORIES } from './tools';
import { Tool, AppView, ToolCategory, ConversionResponse, ErrorResponse } from './types';
import { initUploadZone, renderFileList } from './upload';
import { convert } from './api';

export class App {
  // State
  private currentView: AppView = 'landing';
  private selectedTool: Tool | null = null;
  private files: File[] = [];
  private isConverting = false;
  
  // Cleanup handles
  private cleanupUploadZone: (() => void) | null = null;

  public init(): void {
    this.renderLandingGrid();
    this.bindGlobalEvents();
    window.addEventListener('hashchange', () => this.handleRoute());
    this.handleRoute();
  }

  private bindGlobalEvents(): void {
    document.getElementById('back-btn')?.addEventListener('click', () => this.navigate('/'));
    document.getElementById('new-convert-btn')?.addEventListener('click', () => this.navigate('/'));
    document.getElementById('convert-btn')?.addEventListener('click', () => this.handleConvert());
  }

  private navigate(path: string): void {
    window.location.hash = path;
  }

  private handleRoute(): void {
    const hash = window.location.hash;
    
    if (hash.startsWith('#/tool/')) {
      const toolId = hash.replace('#/tool/', '');
      const tool = TOOLS.find(t => t.id === toolId);
      if (tool) {
        this.selectTool(tool);
        return;
      }
    } else if (hash === '#/result') {
      this.showView('result');
      return;
    }

    this.showView('landing');
  }

  private selectTool(tool: Tool): void {
    this.selectedTool = tool;
    this.files = [];
    this.isConverting = false;
    
    // Update Header
    this.setText('tool-title', tool.name);
    this.setText('tool-desc', tool.description);
    this.setText('tool-icon', tool.icon);
    
    const acceptText = document.getElementById('upload-accept-text');
    if (acceptText) {
      acceptText.textContent = tool.isJsonBody 
        ? 'No file upload required (see options below)' 
        : `Accepted: ${tool.accept.toUpperCase()}`;
    }

    // Render dynamic options
    this.renderToolOptions(tool);

    // Setup Upload Zone
    this.cleanupUploadZone?.(); // Remove old listeners
    const uploadZone = document.getElementById('upload-zone');
    if (uploadZone) {
      uploadZone.style.display = tool.isJsonBody ? 'none' : 'block';
    }
    
    if (!tool.isJsonBody) {
      this.cleanupUploadZone = initUploadZone(tool, {
        onFilesAdded: (files) => this.handleFilesAdded(files),
        onValidationError: (msg) => this.showError(msg),
      });
    }

    this.resetWorkspaceUI();
    this.showView('workspace');
  }

  private handleFilesAdded(newFiles: File[]): void {
    if (!this.selectedTool?.multiple) {
      this.files = [newFiles[0]]; // Replace
    } else {
      this.files = [...this.files, ...newFiles]; // Append
    }
    this.hideError();
    renderFileList(this.files, (idx) => this.removeFile(idx));
    this.updateConvertButton();
  }

  private removeFile(index: number): void {
    this.files.splice(index, 1);
    renderFileList(this.files, (idx) => this.removeFile(idx));
    this.updateConvertButton();
  }

  private updateConvertButton(): void {
    const btn = document.getElementById('convert-btn') as HTMLButtonElement;
    if (!btn) return;

    if (this.isConverting) {
      btn.disabled = true;
      return;
    }

    if (this.selectedTool?.isJsonBody) {
      // HTML to PDF requires at least the HTML field (validation happens on submit)
      btn.disabled = false;
    } else {
      btn.disabled = this.files.length === 0;
    }
  }

  private async handleConvert(): Promise<void> {
    if (!this.selectedTool || this.isConverting) return;
    
    const tool = this.selectedTool;
    const options = this.getFormOptions(tool);

    // Client-side validation for JSON tools
    if (tool.isJsonBody && !options['html']) {
      this.showError('HTML content cannot be empty.');
      return;
    }
    if (!tool.isJsonBody && this.files.length === 0) {
      this.showError('Please upload a file.');
      return;
    }

    this.isConverting = true;
    this.hideError();
    this.setConvertingUI(true);

    try {
      const response = await convert(tool, this.files, options, (progress) => {
        this.updateProgress(progress);
      });

      if (response.success) {
        this.handleSuccess(response as ConversionResponse);
      } else {
        this.showError((response as ErrorResponse).error || 'Conversion failed.');
      }
    } catch (error) {
      const err = error as ErrorResponse;
      this.showError(err.error || 'An unexpected error occurred.');
    } finally {
      this.isConverting = false;
      this.setConvertingUI(false);
    }
  }

  private handleSuccess(result: ConversionResponse): void {
    // Setup Download Button
    const dlBtn = document.getElementById('download-btn') as HTMLAnchorElement;
    if (dlBtn) {
      dlBtn.href = result.download_url;
      dlBtn.download = result.filename;
    }

    // Render Dynamic Stats
    const statsContainer = document.getElementById('result-stats');
    if (statsContainer) {
      let statsHtml = `<div class="stat-item"><strong>Filename:</strong> ${result.filename}</div>`;
      statsHtml += `<div class="stat-item"><strong>Size:</strong> ${result.size_human}</div>`;

      // Tool-specific stats
      const res = result as Record<string, unknown>;
      if ('reduction_percent' in res) {
        statsHtml += `<div class="stat-item"><strong>Reduced by:</strong> ${res.reduction_percent}%</div>`;
      }
      if ('page_count' in res) {
        statsHtml += `<div class="stat-item"><strong>Pages:</strong> ${res.page_count}</div>`;
      }
      if ('tables_found' in res) {
        statsHtml += `<div class="stat-item"><strong>Tables Found:</strong> ${res.tables_found}</div>`;
      }
      if ('rows_extracted' in res) {
        statsHtml += `<div class="stat-item"><strong>Rows Extracted:</strong> ${res.rows_extracted}</div>`;
      }
      if ('slide_count' in res) {
        statsHtml += `<div class="stat-item"><strong>Slides:</strong> ${res.slide_count}</div>`;
      }
      if ('words_detected' in res) {
        statsHtml += `<div class="stat-item"><strong>Words Detected:</strong> ${res.words_detected}</div>`;
      }
      if ('pages_recovered' in res) {
        statsHtml += `<div class="stat-item"><strong>Pages Recovered:</strong> ${res.pages_recovered}</div>`;
      }

      statsContainer.innerHTML = statsHtml;
    }

    this.navigate('/result');
  }

  // ─── UI State Helpers ─────────────────────────────────────────────────

  private setConvertingUI(isConverting: boolean): void {
    const btn = document.getElementById('convert-btn') as HTMLButtonElement;
    const text = btn?.querySelector('.btn-text');
    const loader = btn?.querySelector('.btn-loader');
    const progress = document.getElementById('progress-container');
    
    if (btn) btn.disabled = isConverting;
    if (text) text.style.display = isConverting ? 'none' : 'inline';
    if (loader) loader.style.display = isConverting ? 'inline-block' : 'none';
    if (progress) progress.style.display = isConverting ? 'block' : 'none';
    
    if (!isConverting) {
      this.updateProgress(0);
    }
  }

  private updateProgress(percent: number): void {
    const fill = document.getElementById('progress-fill') as HTMLDivElement;
    const text = document.getElementById('progress-text') as HTMLParagraphElement;
    if (fill) fill.style.width = `${percent}%`;
    if (text) {
      if (percent < 80) text.textContent = 'Uploading file...';
      else if (percent < 100) text.textContent = 'Processing on server...';
      else text.textContent = 'Finishing up...';
    }
  }

  private showError(message: string): void {
    const container = document.getElementById('error-container');
    const text = document.getElementById('error-text');
    if (container && text) {
      text.textContent = message;
      container.style.display = 'flex';
    }
  }

  private hideError(): void {
    const container = document.getElementById('error-container');
    if (container) container.style.display = 'none';
  }

  private resetWorkspaceUI(): void {
    this.hideError();
    this.updateProgress(0);
    document.getElementById('progress-container')!.style.display = 'none';
    document.getElementById('file-list')!.style.display = 'none';
    this.updateConvertButton();
  }

  private getFormOptions(tool: Tool): Record<string, string | number> {
    const opts: Record<string, string | number> = {};
    if (!tool.options) return opts;
    
    tool.options.forEach(opt => {
      const el = document.getElementById(`opt-${opt.id}`) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null;
      if (el) {
        let val: string | number = el.value;
        // Parse numbers and JSON arrays correctly for the backend
        if (opt.type === 'number') {
          val = parseFloat(val) || 0;
        }
        if (opt.id === 'new_order' || opt.id === 'page_numbers') {
          // Don't parse, send as raw JSON string for FastAPI Form()
        }
        opts[opt.id] = val;
      }
    });
    
    return opts;
  }

  // ─── DOM Rendering ────────────────────────────────────────────────────

  private renderLandingGrid(): void {
    const container = document.getElementById('tools-container');
    if (!container) return;

    container.innerHTML = CATEGORIES.map(cat => {
      const tools = TOOLS.filter(t => t.category === cat.id as ToolCategory);
      if (tools.length === 0) return '';
      
      return `
        <div class="category-section">
          <h2 class="category-title">${cat.name}</h2>
          <div class="tools-grid">
            ${tools.map(tool => `
              <a href="#/tool/${tool.id}" class="tool-card glass">
                <span class="tool-icon">${tool.icon}</span>
                <h3 class="tool-name">${tool.name}</h3>
                <p class="tool-desc">${tool.description}</p>
              </a>
            `).join('')}
          </div>
        </div>`;
    }).join('');
  }

  private renderToolOptions(tool: Tool): void {
    const container = document.getElementById('options-container') as HTMLDivElement;
    if (!container) return;

    if (!tool.options || tool.options.length === 0) {
      container.style.display = 'none';
      return;
    }

    container.style.display = 'block';
    container.innerHTML = tool.options.map(opt => {
      if (opt.type === 'select') {
        const optsHtml = (opt.options || []).map(o => 
          `<option value="${o.value}" ${o.value === opt.value ? 'selected' : ''}>${o.label}</option>`
        ).join('');
        return `<div class="form-group"><label for="opt-${opt.id}">${opt.label}</label><select id="opt-${opt.id}" name="${opt.id}">${optsHtml}</select></div>`;
      }
      if (opt.type === 'textarea') {
        return `<div class="form-group"><label for="opt-${opt.id}">${opt.label}</label><textarea id="opt-${opt.id}" name="${opt.id}" rows="6">${opt.value}</textarea></div>`;
      }
      return `<div class="form-group"><label for="opt-${opt.id}">${opt.label}</label><input type="${opt.type}" id="opt-${opt.id}" name="${opt.id}" value="${opt.value}" ${opt.required ? 'required' : ''} /></div>`;
    }).join('');
  }

  // ─── Utilities ────────────────────────────────────────────────────────

  private showView(view: AppView): void {
    this.currentView = view;
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    document.getElementById(`${view}-view`)?.classList.add('active');
    window.scrollTo(0, 0);
  }

  private setText(id: string, text: string): void {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }
}
