/**
 * Master TypeScript definitions for ConvertX.
 * These types strictly mirror the Pydantic response_models.py and route expectations.
 * If the backend changes, update this file first — TypeScript will catch every breaking change.
 */

// ═══════════════════════════════════════════════════════════════════════════════
// Tool Configuration
// ═══════════════════════════════════════════════════════════════════════════════

export type ToolCategory = 
  | 'pdf-tools' 
  | 'convert-from-pdf' 
  | 'convert-to-pdf' 
  | 'advanced' 
  | 'image-tools';

export interface ToolOption {
  id: string;
  label: string;
  type: 'text' | 'number' | 'select' | 'textarea';
  value: string | number;
  placeholder?: string;
  options?: { label: string; value: string | number }[];
  required?: boolean;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  icon: string; // SVG path or emoji
  category: ToolCategory;
  endpoint: string;
  accept: string; // MIME types for input accept attribute
  multiple: boolean;
  options?: ToolOption[];
  isJsonBody?: boolean; // True for HTML to PDF
}

// ═══════════════════════════════════════════════════════════════════════════════
// API Responses (Mirrors backend/utils/response_models.py)
// ═══════════════════════════════════════════════════════════════════════════════

export interface ConversionResponse {
  success: boolean;
  download_url: string;
  filename: string;
  size_bytes: number;
  size_human: string;
}

export interface ImageToPdfResponse extends ConversionResponse { page_count: number; }
export interface ImageToExcelResponse extends ConversionResponse { rows_extracted: number; }
export interface CompressPdfResponse extends ConversionResponse { original_size_bytes: number; compressed_size_bytes: number; reduction_percent: number; }
export interface SplitPdfResponse extends ConversionResponse { page_count: number; }
export interface PdfToImageResponse extends ConversionResponse { page_count: number; }
export interface PdfToExcelResponse extends ConversionResponse { tables_found: number; rows_extracted: number; }
export interface PdfToPowerPointResponse extends ConversionResponse { slide_count: number; }
export interface OcrPdfResponse extends ConversionResponse { pages_processed: number; words_detected: number; }
export interface RepairPdfResponse extends ConversionResponse { pages_recovered: number; }

export interface ErrorResponse {
  success: false;
  error: string;
  detail: string;
}

export type ApiResponse = ConversionResponse | ErrorResponse;

// ═══════════════════════════════════════════════════════════════════════════════
// Application State
// ═══════════════════════════════════════════════════════════════════════════════

export type AppView = 'landing' | 'workspace' | 'result';

export interface AppState {
  currentView: AppView;
  selectedTool: Tool | null;
  files: File[];
  isConverting: boolean;
  progress: number;
  result: ConversionResponse | null;
  error: string | null;
}
