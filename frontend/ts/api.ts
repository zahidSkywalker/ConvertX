/**
 * API Client — Constructs exact payloads expected by the FastAPI backend.
 * 
 * Handles 4 distinct payload shapes:
 * 1. Single file + Form options (Rotate, Watermark, Compress, etc.)
 * 2. Multiple files (Merge PDF, Image to PDF)
 * 3. Single file + Multiple image files + JSON string (Edit PDF)
 * 4. Raw JSON body (HTML to PDF)
 * 
 * Uses XHR for multipart to provide real byte-level upload progress.
 */

import { Tool, ApiResponse, ErrorResponse } from './types';

type ProgressCallback = (percent: number) => void;

export async function convert(
  tool: Tool, 
  files: File[], 
  options: Record<string, string | number>,
  onProgress: ProgressCallback
): Promise<ApiResponse> {
  
  // Shape 4: JSON Body (HTML to PDF)
  if (tool.isJsonBody) {
    return fetchJson(tool, options, onProgress);
  }

  // Shapes 1, 2, 3: Multipart Form Data
  return fetchMultipart(tool, files, options, onProgress);
}

async function fetchJson(
  tool: Tool, 
  options: Record<string, string | number>,
  onProgress: ProgressCallback
): Promise<ApiResponse> {
  onProgress(10);
  
  const payload: Record<string, string> = {};
  if (options['html']) payload.html = String(options['html']);
  if (options['css']) payload.css = String(options['css']);

  try {
    const response = await fetch(tool.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    onProgress(90);
    const data = await response.json();
    onProgress(100);
    
    if (!response.ok) throw data;
    return data as ApiResponse;
  } catch (error) {
    onProgress(100);
    throw handleApiError(error);
  }
}

function fetchMultipart(
  tool: Tool, 
  files: File[], 
  options: Record<string, string | number>,
  onProgress: ProgressCallback
): Promise<ApiResponse> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    
    // Append Files based on tool requirements
    if (tool.id === 'edit-pdf') {
      formData.append('file', files[0]);
      if (files.length > 1) {
        for (let i = 1; i < files.length; i++) {
          formData.append('images', files[i]);
        }
      }
      formData.append('operations', String(options['operations'] || '[]')); 
    } else if (tool.multiple) {
      files.forEach(f => formData.append('files', f));
    } else {
      formData.append('file', files[0]);
    }

    // Append Options as Form fields (skip internal keys)
    for (const [key, value] of Object.entries(options)) {
      if (key === 'operations') continue; // Already appended above for edit-pdf
      if (value !== '' && value !== undefined) {
        formData.append(key, String(value));
      }
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', tool.endpoint, true);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 80);
        onProgress(percent);
      }
    };

    xhr.onload = () => {
      onProgress(100);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as ApiResponse);
        } catch {
          reject({ success: false, error: 'Invalid JSON response from server.', detail: xhr.responseText.substring(0, 200) } as ErrorResponse);
        }
      } else {
        // Try to parse as JSON (our error format)
        try {
          const parsed = JSON.parse(xhr.responseText);
          reject(parsed as ErrorResponse);
        } catch {
          // Non-JSON response (e.g., Vercel 404 HTML page, proxy error, etc.)
          if (xhr.status === 404) {
            reject({ 
              success: false, 
              error: 'API endpoint not found. The backend may not be configured correctly.', 
              detail: 'Ensure BACKEND_URL is set in your Vercel environment variables.' 
            } as ErrorResponse);
          } else if (xhr.status === 0) {
            reject({ 
              success: false, 
              error: 'Network error. The backend may be down or blocked by CORS.', 
              detail: 'Check that the backend is running and ALLOWED_ORIGINS includes your frontend domain.' 
            } as ErrorResponse);
          } else {
            reject({ 
              success: false, 
              error: `Server error (${xhr.status}).`, 
              detail: xhr.statusText || 'Unknown error' 
            } as ErrorResponse);
          }
        }
      }
    };

    xhr.onerror = () => {
      onProgress(100);
      reject({ 
        success: false, 
        error: 'Network error. The backend may be down or blocked by CORS.', 
        detail: 'Check that the backend is running and ALLOWED_ORIGINS includes your frontend domain.' 
      } as ErrorResponse);
    };

    xhr.ontimeout = () => {
      onProgress(100);
      reject({ 
        success: false, 
        error: 'Request timed out. The file may be too large or the server is slow.', 
        detail: '' 
      } as ErrorResponse);
    };

    xhr.timeout = 300000; // 5 minute timeout for large files
    xhr.send(formData);
  });
}

function handleApiError(error: unknown): ErrorResponse {
  if (typeof error === 'object' && error !== null && 'error' in error) {
    return error as ErrorResponse;
  }
  return { success: false, error: 'An unexpected error occurred.', detail: String(error) };
}
