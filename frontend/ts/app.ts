/**
 * ConvertX Application Shell — Production Version.
 * 
 * Fixed: resetWorkspaceUI now hides options container.
 * Fixed: Error handling properly resets all UI state.
 * Fixed: Select default value comparison uses String coercion.
 */
import { TOOLS, CATEGORIES } from './tools';
import { Tool, AppView, ToolCategory, ConversionResponse, ErrorResponse } from './types';
import { initUploadZone, renderFileList } from './upload';
import { convert } from './api';

export class App {
  // State
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
    
    this.setText('tool-title', tool.name);
    this.setText('tool-desc', tool.description);
    this.setText('tool-icon', tool.icon);
    
    const acceptText = document.getElementById('upload-accept-text');
    if (acceptText) {
      acceptText.textContent = tool.isJsonBody 
        ? 'No file upload required — enter content in the options below' 
        : `Accepted: ${tool.accept.toUpperCase()}`;
    }

    // Reset ALL workspace UI FIRST — this hides everything
    this.resetWorkspaceUI();

    // Then render tool-specific options (shows container only if options exist)
    this.renderToolOptions(tool);

    // Setup upload zone
    this.cleanupUploadZone?.(); 
    const uploadZone = document.getElementById('upload-zone');
    if (uploadZone) {
      if (tool.isJsonBody) {
        uploadZone.classList.add('hidden');
      } else {
        uploadZone.classList.remove('hidden');
      }
    }
    
    if (!tool.isJsonBody) {
      this.cleanupUploadZone = initUploadZone(tool, {
        onFilesAdded: (files) => this.handleFilesAdded(files),
        onValidationError: (msg) => this.showError(msg),
      });
    }

    this.showView('workspace');
  }

  private handleFilesAdded(newFiles: File[]): void {
    if (!this.selectedTool?.multiple) {
      this.files = [newFiles[0]]; 
    } else {
      this.files = [...this.files, ...newFiles]; 
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
      btn.disabled = false;
    } else {
      btn.disabled = this.files.length === 0;
    }
  }

  private async handleConvert(): Promise<void> {
    if (!this.selectedTool || this.isConverting) return;
    
    const tool = this.selectedTool;
    const options = this.getFormOptions(tool);

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
    const dlBtn = document.getElementById('download-btn') as HTMLAnchorElement;
    if (dlBtn) {
      dlBtn.href = result.download_url;
      dlBtn.download = result.filename;
    }

    const statsContainer = document.getElementById('result-stats');
    if (statsContainer) {
      let statsHtml = `<div class="stat-item"><strong>Filename:</strong> ${this.escapeHtml(result.filename)}</div>`;
      statsHtml += `<div class="stat-item"><strong>Size:</strong> ${this.escapeHtml(result.size_human)}</div>`;

      const res = result as unknown as Record<string, unknown>;
      
      if ('reduction_percent' in res) statsHtml += `<div class="stat-item"><strong>Reduced by:</strong> ${res.reduction_percent}%</div>`;
      if ('page_count' in res) statsHtml += `<div class="stat-item"><strong>Pages:</strong> ${res.page_count}</div>`;
      if ('tables_found' in res) statsHtml += `<div class="stat-item"><strong>Tables Found:</strong> ${res.tables_found}</div>`;
      if ('rows_extracted' in res) statsHtml += `<div class="stat-item"><strong>Rows Extracted:</strong> ${res.rows_extracted}</div>`;
      if ('slide_count' in res) statsHtml += `<div class="stat-item"><strong>Slides:</strong> ${res.slide_count}</div>`;
      if ('words_detected' in res) statsHtml += `<div class="stat-item"><strong>Words Detected:</strong> ${res.words_detected}</div>`;
      if ('pages_processed' in res) statsHtml += `<div class="stat-item"><strong>Pages Processed:</strong> ${res.pages_processed}</div>`;
      if ('pages_recovered' in res) statsHtml += `<div class="stat-item"><strong>Pages Recovered:</strong> ${res.pages_recovered}</div>`;

      statsContainer.innerHTML = statsHtml;
    }

    this.navigate('/result');
  }

  private setConvertingUI(isConverting: boolean): void {
    const btn = document.getElementById('convert-btn') as HTMLButtonElement;
    const text = btn?.querySelector('.btn-text');
    const loader = btn?.querySelector('.btn-loader');
    const progress = document.getElementById('progress-container');
    
    if (btn) btn.disabled = isConverting;
    
    if (text) {
      if (isConverting) text.classList.add('hidden'); else text.classList.remove('hidden');
    }
    if (loader) {
      if (isConverting) loader.classList.remove('hidden'); else loader.classList.add('hidden');
    }
    if (progress) {
      if (isConverting) progress.classList.remove('hidden'); else progress.classList.add('hidden');
    }
    
    if (!isConverting) this.updateProgress(0);
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
      container.classList.remove('hidden');
    }
  }

  private hideError(): void {
    const container = document.getElementById('error-container');
    if (container) container.classList.add('hidden');
  }

  private resetWorkspaceUI(): void {
    this.hideError();
    this.updateProgress(0);
    
    // Hide ALL toggleable elements
    const pc = document.getElementById('progress-container');
    if (pc) pc.classList.add('hidden');
    
    const fl = document.getElementById('file-list');
    if (fl) fl.classList.add('hidden');

    // FIX: Also hide options container — this was the watermark bleeding bug
    const oc = document.getElementById('options-container');
    if (oc) oc.classList.add('hidden');

    this.updateConvertButton();
  }

  private getFormOptions(tool: Tool): Record<string, string | number> {
    const opts: Record<string, string | number> = {};
    if (!tool.options) return opts;
    
    tool.options.forEach(opt => {
      const el = document.getElementById(`opt-${opt.id}`) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null;
      if (el) {
        let val: string | number = el.value;
        if (opt.type === 'number') {
          val = parseFloat(val) || 0;
        }
        opts[opt.id] = val;
      }
    });
    
    return opts;
  }

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
      container.classList.add('hidden');
      return;
    }

    container.classList.remove('hidden');
    container.innerHTML = tool.options.map(opt => {
      if (opt.type === 'select') {
        const optsHtml = (opt.options || []).map(o => 
          // FIX: Use String() coercion so number values match correctly
          `<option value="${o.value}" ${String(o.value) === String(opt.value) ? 'selected' : ''}>${o.label}</option>`
        ).join('');
        return `<div class="form-group"><label for="opt-${opt.id}">${opt.label}</label><select id="opt-${opt.id}" name="${opt.id}">${optsHtml}</select></div>`;
      }
      if (opt.type === 'textarea') {
        return `<div class="form-group"><label for="opt-${opt.id}">${opt.label}</label><textarea id="opt-${opt.id}" name="${opt.id}" rows="6">${opt.value}</textarea></div>`;
      }
      return `<div class="form-group"><label for="opt-${opt.id}">${opt.label}</label><input type="${opt.type}" id="opt-${opt.id}" name="${opt.id}" value="${opt.value}" ${opt.required ? 'required' : ''} placeholder="${opt.placeholder || ''}" /></div>`;
    }).join('');
  }

  private showView(view: AppView): void {
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    document.getElementById(`${view}-view`)?.classList.add('active');
    window.scrollTo(0, 0);
  }

  private setText(id: string, text: string): void {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  private escapeHtml(str: string): string {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
}
