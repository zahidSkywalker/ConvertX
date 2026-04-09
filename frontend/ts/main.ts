/**
 * Application Entry Point.
 * Initializes Vite HMR in dev, registers Service Worker, and boots the App.
 */
import './style.css';
import { App } from './app';
import { initTheme } from './theme';

// Boot
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  const app = new App();
  app.init();

  // Register Service Worker for PWA (only in production)
  if ('serviceWorker' in navigator && import.meta.env.PROD) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js').catch(() => {
        // SW registration failed, likely due to ad-blockers or older browsers
        console.warn('SW registration failed.');
      });
    });
  }
});
