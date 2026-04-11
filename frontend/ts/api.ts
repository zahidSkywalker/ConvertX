/**
 * API Client — Calls backend directly via VITE_BACKEND_URL env var.
 * 
 * Vite automatically exposes any env var prefixed with VITE_ at build time.
 * No proxy needed — simpler, more reliable, easier to debug.
 */

import { Tool, ApiResponse, ErrorResponse } from './types';

// Runtime backend URL. Falls back to empty (for local dev with Vite proxy).
const BACKEND_URL: string = import.meta.env.VITE_BACKEND_URL || '';

type ProgressCallback = (percent: number) => void;

export async function convert(
  tool: Tool, 
  files: File[], 
  options: Record<string, string | number>,
  onProgress: ProgressCallback
): Promise<ApiResponse> {
  
  if (tool.isJsonBody) {
    return fetchJson(tool, options, onProgress);
  }

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
    const response = await fetch(`${BACKEND_URL}${tool.endpoint}`, {
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

    for (const [key, value] of Object.entries(options)) {
      if (key === 'operations') continue;
      if (value !== '' && value !== undefined) {
        formData.append(key, String(value));
      }
    }

    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BACKEND_URL}${tool.endpoint}`, true);

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
        try {
          reject(JSON.parse(xhr.responseText) as ErrorResponse);
        } catch {
          if (xhr.status === 0) {
            reject({ 
              success: false, 
              error: 'Network error — could not reach the backend.', 
              detail: 'Your backend might be sleeping (Render cold start) or the VITE_BACKEND_URL is wrong.' 
            } as ErrorResponse);
          } else {
            reject({ 
              success: false, 
              error: `Backend returned error ${xhr.status}.`, 
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
        error: 'Network error — could not reach the backend.', 
        detail: 'Your backend might be sleeping (Render cold start takes ~30s). Try again in a moment, or check VITE_BACKEND_URL.' 
      } as ErrorResponse);
    };

    xhr.ontimeout = () => {
      onProgress(100);
      reject({ 
        success: false, 
        error: 'Request timed out.', 
        detail: 'The file may be too large or the backend is slow to respond.' 
      } as ErrorResponse);
    };

    xhr.timeout = 300000; // 5 minutes
    xhr.send(formData);
  });
}

function handleApiError(error: unknown): ErrorResponse {
  if (typeof error === 'object' && error !== null && 'error' in error) {
    return error as ErrorResponse;
  }
  return { success: false, error: 'An unexpected error occurred.', detail: String(error) };
}
