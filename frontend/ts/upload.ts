/**
 * Upload Management — Drag/Drop, File Validation, and UI Rendering.
 * Handles the quirks of mobile file pickers and drag event bubbling.
 */
import { Tool } from './types';

const MAX_SIZE_BYTES = 10 * 1024 * 1024; // 10MB

interface UploadCallbacks {
  onFilesAdded: (files: File[]) => void;
  onValidationError: (message: string) => void;
}

export function initUploadZone(tool: Tool, callbacks: UploadCallbacks): () => void {
  const zone = document.getElementById('upload-zone') as HTMLElement;
  const input = document.getElementById('file-input') as HTMLInputElement;
  
  if (!zone || !input) return () => {};

  let dragCounter = 0; // Prevents flickering when dragging over child elements

  const handleDragEnter = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter++;
    zone.classList.add('drag-over');
  };

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter--;
    if (dragCounter === 0) zone.classList.remove('drag-over');
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter = 0;
    zone.classList.remove('drag-over');
    
    if (e.dataTransfer?.files) {
      processFiles(e.dataTransfer.files, tool, callbacks);
    }
  };

  const handleClick = () => {
    // For HTML to PDF, we don't need file upload
    if (tool.isJsonBody) return;
    input.click();
  };

  const handleChange = () => {
    if (input.files) {
      processFiles(input.files, tool, callbacks);
      input.value = ''; // Reset so same file can be selected again
    }
  };

  // Bind events
  zone.addEventListener('dragenter', handleDragEnter);
  zone.addEventListener('dragleave', handleDragLeave);
  zone.addEventListener('dragover', handleDragOver);
  zone.addEventListener('drop', handleDrop);
  zone.addEventListener('click', handleClick);
  input.addEventListener('change', handleChange);

  // Return cleanup function
  return () => {
    zone.removeEventListener('dragenter', handleDragEnter);
    zone.removeEventListener('dragleave', handleDragLeave);
    zone.removeEventListener('dragover', handleDragOver);
    zone.removeEventListener('drop', handleDrop);
    zone.removeEventListener('click', handleClick);
    input.removeEventListener('change', handleChange);
  };
}

function processFiles(fileList: FileList, tool: Tool, callbacks: UploadCallbacks): void {
  const validFiles: File[] = [];
  const allowedExts = tool.accept.split(',').map(e => e.trim().toLowerCase());

  for (let i = 0; i < fileList.length; i++) {
    const file = fileList[i];
    const fileExt = '.' + file.name.split('.').pop()?.toLowerCase();

    if (!allowedExts.includes(fileExt)) {
      callbacks.onValidationError(`Invalid file type: ${file.name}. Allowed: ${tool.accept.toUpperCase()}`);
      return;
    }

    if (file.size > MAX_SIZE_BYTES) {
      callbacks.onValidationError(`File too large: ${file.name} (${(file.size / (1024 * 1024)).toFixed(1)}MB). Maximum is 10MB.`);
      return;
    }

    if (file.size === 0) {
      callbacks.onValidationError(`File is empty: ${file.name}`);
      return;
    }

    validFiles.push(file);
  }

  if (!tool.multiple && validFiles.length > 1) {
    callbacks.onValidationError('This tool only accepts a single file.');
    return;
  }

  if (validFiles.length > 0) {
    callbacks.onFilesAdded(validFiles);
  }
}

export function renderFileList(files: File[], onRemove: (index: number) => void): void {
  const list = document.getElementById('file-list') as HTMLUListElement;
  if (!list) return;

  if (files.length === 0) {
    list.style.display = 'none';
    return;
  }

  list.style.display = 'block';
  list.innerHTML = files.map((file, idx) => `
    <li class="file-item">
      <span>📄 ${file.name} (${formatSize(file.size)})</span>
      <button class="file-item-remove" data-index="${idx}" title="Remove">&times;</button>
    </li>
  `).join('');

  // Bind remove buttons
  list.querySelectorAll('.file-item-remove').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const index = parseInt((e.currentTarget as HTMLElement).dataset.index || '0', 10);
      onRemove(index);
    });
  });
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}
