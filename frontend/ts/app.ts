/**
 * ConvertX Application Shell.
 * Hash-based router, view management, and static DOM rendering.
 * Phase 5 will add the dynamic upload/API logic to this class.
 */
import { TOOLS, CATEGORIES } from './tools';
import { Tool, AppView, ToolCategory } from './types';

export class App {
  private state = {
    currentView: 'landing' as AppView,
    selectedTool: null as Tool | null,
  };

  public init(): void {
    this.renderLandingGrid();
    this.bindBaseEvents();
    window.addEventListener('hashchange', () => this.handleRoute());
    this.handleRoute(); // Initial route check
  }

  private bindBaseEvents(): void {
    const backBtn = document.getElementById('back-btn');
    if (backBtn) backBtn.addEventListener('click', () => window.location.hash = '/');
    
    const newConvBtn = document.getElementById('new-convert-btn');
    if (newConvBtn) newConvBtn.addEventListener('click', () => window.location.hash = '/');
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
    this.state.selectedTool = tool;
    
    // Update workspace UI statically
    const title = document.getElementById('tool-title');
    const desc = document.getElementById('tool-desc');
    const icon = document.getElementById('tool-icon');
    const acceptText = document.getElementById('upload-accept-text');
    
    if (title) title.textContent = tool.name;
    if (desc) desc.textContent = tool.description;
    if (icon) icon.textContent = tool.icon;
    if (acceptText) acceptText.textContent = tool.accept ? `Accepted: ${tool.accept.toUpperCase()}` : 'No file upload required (HTML input)';

    this.renderToolOptions(tool);
    this.showView('workspace');
    this.resetWorkspaceState();
  }

  private renderToolOptions(tool: Tool): void {
    const container = document.getElementById('options-container');
    if (!container) return;

    if (!tool.options || tool.options.length === 0) {
      container.style.display = 'none';
      return;
    }

    container.style.display = 'block';
    container.innerHTML = tool.options.map(opt => {
      if (opt.type === 'select') {
        const optionsHtml = opt.options?.map(o => 
          `<option value="${o.value}" ${o.value === opt.value ? 'selected' : ''}>${o.label}</option>`
        ).join('');
        return `
          <div class="form-group">
            <label for="${opt.id}">${opt.label}</label>
            <select id="opt-${opt.id}" name="${opt.id}">${optionsHtml}</select>
          </div>`;
      }
      if (opt.type === 'textarea') {
        return `
          <div class="form-group">
            <label for="${opt.id}">${opt.label}</label>
            <textarea id="opt-${opt.id}" name="${opt.id}" rows="6" placeholder="${opt.placeholder || ''}">${opt.value}</textarea>
          </div>`;
      }
      return `
        <div class="form-group">
          <label for="${opt.id}">${opt.label}</label>
          <input type="${opt.type}" id="opt-${opt.id}" name="${opt.id}" 
                 value="${opt.value}" placeholder="${opt.placeholder || ''}" 
                 ${opt.required ? 'required' : ''} />
        </div>`;
    }).join('');
  }

  private renderLandingGrid(): void {
    const container = document.getElementById('tools-container');
    if (!container) return;

    const html = CATEGORIES.map(cat => {
      const tools = TOOLS.filter(t => t.category === cat.id as ToolCategory);
      if (tools.length === 0) return '';
      
      return `
        <div class="category-section">
          <h2 class="category-title">${cat.name}</h2>
          <div class="tools-grid">
            ${tools.map(tool => `
              <a href="#/tool/${tool.id}" class="tool-card glass" data-tool="${tool.id}">
                <span class="tool-icon">${tool.icon}</span>
                <h3 class="tool-name">${tool.name}</h3>
                <p class="tool-desc">${tool.description}</p>
              </a>
            `).join('')}
          </div>
        </div>`;
    }).join('');

    container.innerHTML = html;
  }

  private showView(view: AppView): void {
    this.state.currentView = view;
    document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
    document.getElementById(`${view}-view`)?.classList.add('active');
    window.scrollTo(0, 0);
  }

  private resetWorkspaceState(): void {
    const fileList = document.getElementById('file-list');
    const errorContainer = document.getElementById('error-container');
    const progressContainer = document.getElementById('progress-container');
    
    if (fileList) fileList.style.display = 'none';
    if (errorContainer) errorContainer.style.display = 'none';
    if (progressContainer) progressContainer.style.display = 'none';
  }
}
