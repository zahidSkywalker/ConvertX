/**
 * Tool Registry — Single source of truth for the 19 tools.
 * The frontend reads this array to render the landing page grid,
 * configure the upload zone, and build the API request.
 */
import { Tool } from './types';

export const TOOLS: Tool[] = [
  // ─── PDF Tools ─────────────────────────────────────────────────────────
  {
    id: 'merge-pdf', name: 'Merge PDF', description: 'Combine multiple PDFs into one.',
    icon: '📂', category: 'pdf-tools', endpoint: '/api/merge-pdf',
    accept: '.pdf', multiple: true,
  },
  {
    id: 'split-pdf', name: 'Split PDF', description: 'Separate a PDF into individual pages.',
    icon: '✂️', category: 'pdf-tools', endpoint: '/api/split-pdf',
    accept: '.pdf', multiple: false,
  },
  {
    id: 'compress-pdf', name: 'Compress PDF', description: 'Reduce PDF file size losslessly.',
    icon: '📦', category: 'pdf-tools', endpoint: '/api/compress-pdf',
    accept: '.pdf', multiple: false,
  },
  {
    id: 'rotate-pdf', name: 'Rotate PDF', description: 'Rotate pages by 90, 180, or 270 degrees.',
    icon: '🔄', category: 'pdf-tools', endpoint: '/api/rotate-pdf',
    accept: '.pdf', multiple: false,
    options: [
      { id: 'degrees', label: 'Rotation', type: 'select', value: 90, options: [{label:'90°', value:90},{label:'180°', value:180},{label:'270°', value:270}] },
      { id: 'page_numbers', label: 'Specific Pages (JSON)', type: 'text', value: '', placeholder: 'e.g. [1, 3, 5]. Leave empty for all.' }
    ],
  },
  {
    id: 'watermark-pdf', name: 'Watermark PDF', description: 'Add diagonal text watermark.',
    icon: '💧', category: 'pdf-tools', endpoint: '/api/watermark-pdf',
    accept: '.pdf', multiple: false,
    options: [
      { id: 'watermark_text', label: 'Watermark Text', type: 'text', value: 'CONFIDENTIAL', required: true },
      { id: 'opacity', label: 'Opacity (0.05 - 1.0)', type: 'number', value: 0.3 },
      { id: 'angle', label: 'Angle (degrees)', type: 'number', value: 45 },
    ],
  },
  {
    id: 'add-page-numbers', name: 'Page Numbers', description: 'Insert "Page X of Y" to footer.',
    icon: '🔢', category: 'pdf-tools', endpoint: '/api/add-page-numbers',
    accept: '.pdf', multiple: false,
    options: [
      { id: 'position', label: 'Position', type: 'select', value: 'bottom-center', options: [
        {label:'Bottom Center', value:'bottom-center'}, {label:'Bottom Left', value:'bottom-left'}, {label:'Bottom Right', value:'bottom-right'},
        {label:'Top Center', value:'top-center'}, {label:'Top Left', value:'top-left'}, {label:'Top Right', value:'top-right'}
      ]}
    ],
  },
  {
    id: 'organize-pages', name: 'Organize Pages', description: 'Delete, reorder, or duplicate pages.',
    icon: '📑', category: 'pdf-tools', endpoint: '/api/organize-pages',
    accept: '.pdf', multiple: false,
    options: [
      { id: 'new_order', label: 'New Page Order (JSON)', type: 'text', value: '', placeholder: 'e.g. [3, 1, 2, 2]', required: true }
    ],
  },
  {
    id: 'repair-pdf', name: 'Repair PDF', description: 'Fix corrupted PDFs and broken structures.',
    icon: '🛠️', category: 'pdf-tools', endpoint: '/api/repair-pdf',
    accept: '.pdf', multiple: false,
  },
  {
    id: 'pdf-to-image', name: 'PDF to Image', description: 'Convert PDF pages to high-res PNGs.',
    icon: '🖼️', category: 'pdf-tools', endpoint: '/api/pdf-to-image',
    accept: '.pdf', multiple: false,
  },

  // ─── Convert FROM PDF ──────────────────────────────────────────────────
  {
    id: 'pdf-to-word', name: 'PDF to Word', description: 'Extract layout to .docx.',
    icon: '📝', category: 'convert-from-pdf', endpoint: '/api/pdf-to-word',
    accept: '.pdf', multiple: false,
  },
  {
    id: 'pdf-to-excel', name: 'PDF to Excel', description: 'Extract tables to .xlsx.',
    icon: '📊', category: 'convert-from-pdf', endpoint: '/api/pdf-to-excel',
    accept: '.pdf', multiple: false,
  },
  {
    id: 'pdf-to-powerpoint', name: 'PDF to PowerPoint', description: 'Extract content to .pptx slides.',
    icon: '📈', category: 'convert-from-pdf', endpoint: '/api/pdf-to-powerpoint',
    accept: '.pdf', multiple: false,
  },

  // ─── Convert TO PDF ────────────────────────────────────────────────────
  {
    id: 'word-to-pdf', name: 'Word to PDF', description: 'Convert .docx to PDF.',
    icon: '📄', category: 'convert-to-pdf', endpoint: '/api/word-to-pdf',
    accept: '.docx', multiple: false,
  },
  {
    id: 'excel-to-pdf', name: 'Excel to PDF', description: 'Convert .xlsx to PDF.',
    icon: '📋', category: 'convert-to-pdf', endpoint: '/api/excel-to-pdf',
    accept: '.xlsx', multiple: false,
  },
  {
    id: 'powerpoint-to-pdf', name: 'PowerPoint to PDF', description: 'Convert .pptx to PDF.',
    icon: '📽️', category: 'convert-to-pdf', endpoint: '/api/powerpoint-to-pdf',
    accept: '.pptx', multiple: false,
  },
  {
    id: 'image-to-pdf', name: 'Image to PDF', description: 'Stitch multiple images into one PDF.',
    icon: '🖼️', category: 'convert-to-pdf', endpoint: '/api/image-to-pdf',
    accept: '.jpg,.jpeg,.png,.webp', multiple: true,
  },
  {
    id: 'html-to-pdf', name: 'HTML to PDF', description: 'Render HTML/CSS to PDF.',
    icon: '🌐', category: 'convert-to-pdf', endpoint: '/api/html-to-pdf',
    accept: '', multiple: false, isJsonBody: true,
    options: [
      { id: 'html', label: 'HTML Code', type: 'textarea', value: '<h1>Hello ConvertX</h1>', required: true },
      { id: 'css', label: 'CSS Code (Optional)', type: 'textarea', value: 'body { font-family: sans-serif; color: #333; }' }
    ],
  },

  // ─── Advanced ──────────────────────────────────────────────────────────
  {
    id: 'edit-pdf', name: 'Edit PDF', description: 'Add text and images to PDF.',
    icon: '✏️', category: 'advanced', endpoint: '/api/edit-pdf',
    accept: '.pdf', multiple: false,
  },
  {
    id: 'ocr-pdf', name: 'OCR PDF', description: 'Make scanned PDFs searchable/selectable.',
    icon: '👁️', category: 'advanced', endpoint: '/api/ocr-pdf',
    accept: '.pdf', multiple: false,
  },

  // ─── Image Tools ───────────────────────────────────────────────────────
  {
    id: 'image-to-excel', name: 'Image to Excel', description: 'Extract table data via OCR.',
    icon: '📷', category: 'image-tools', endpoint: '/api/image-to-excel',
    accept: '.jpg,.jpeg,.png,.webp', multiple: false,
  },
];

export const CATEGORIES = [
  { id: 'pdf-tools', name: 'PDF Tools' },
  { id: 'convert-from-pdf', name: 'Convert from PDF' },
  { id: 'convert-to-pdf', name: 'Convert to PDF' },
  { id: 'advanced', name: 'Advanced Tools' },
  { id: 'image-tools', name: 'Image Tools' },
];
