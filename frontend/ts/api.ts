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
  onProgress(10); // Simulate start
  
  // Sanitize the payload to only include our defined options
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
      // Shape 3: Base file + images array + JSON operations
      formData.append('file', files[0]);
      // Note: image files would be added here if frontend had image upload UI
      // For now, we send an empty array if no extra images provided
      formData.append('operations', JSON.stringify([])); 
    } else if (tool.multiple) {
      // Shape 2: Multiple files
      files.forEach(f => formData.append('files', f));
    } else {
      // Shape 1: Single file
      formData.append('file', files[0]);
    }

    // Append Options as Form fields
    for (const [key, value] of Object.entries(options)) {
      if (value !== '' && value !== undefined) {
        formData.append(key, String(value));
      }
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', tool.endpoint, true);

    // Real byte-level upload progress
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 80); // 80% for upload
        onProgress(percent);
      }
    };

    xhr.onload = () => {
      onProgress(100);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as ApiResponse);
        } catch {
          reject({ success: false, error: 'Invalid JSON response from server.', detail: xhr.responseText } as ErrorResponse);
        }
      } else {
        try {
          reject(JSON.parse(xhr.responseText) as ErrorResponse);
        } catch {
          reject({ success: false, error: `Server error (${xhr.status})`, detail: xhr.statusText } as ErrorResponse);
        }
      }
    };

    xhr.onerror = () => {
      onProgress(100);
      reject({ success: false, error: 'Network error. Please check your connection.', detail: '' } as ErrorResponse);
    };

    xhr.send(formData);
  });
}

function handleApiError(error: unknown): ErrorResponse {
  if (typeof error === 'object' && error !== null && 'error' in error) {
    return error as ErrorResponse;
  }
  return { success: false, error: 'An unexpected error occurred.', detail: String(error) };
}
