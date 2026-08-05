import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './index.css';

const container = document.getElementById('root');
if (!container) throw new Error('Root element #root not found');
const root = createRoot(container);

window.addEventListener('error', (event) => {
  console.error('Unhandled error during app startup:', event.error ?? event.message, event.error);
});
window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled promise rejection during app startup:', event.reason);
});

try {
  root.render(<App />);
} catch (error) {
  console.error('Failed to mount React application:', error);
  container.innerHTML = `
    <div style="padding: 24px; font-family: system-ui, sans-serif; color: #c92a2a; background: #fff7f7; min-height: 100vh;">
      <h1>Application failed to start</h1>
      <p>Please check the browser console for details.</p>
    </div>
  `;
}
