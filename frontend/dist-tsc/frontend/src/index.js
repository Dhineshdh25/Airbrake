"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const jsx_runtime_1 = require("react/jsx-runtime");
const client_1 = require("react-dom/client");
const App_1 = __importDefault(require("./App"));
require("./index.css");
const container = document.getElementById('root');
if (!container)
    throw new Error('Root element #root not found');
const root = (0, client_1.createRoot)(container);
window.addEventListener('error', (event) => {
    console.error('Unhandled error during app startup:', event.error ?? event.message, event.error);
});
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection during app startup:', event.reason);
});
try {
    root.render((0, jsx_runtime_1.jsx)(App_1.default, {}));
}
catch (error) {
    console.error('Failed to mount React application:', error);
    container.innerHTML = `
    <div style="padding: 24px; font-family: system-ui, sans-serif; color: #c92a2a; background: #fff7f7; min-height: 100vh;">
      <h1>Application failed to start</h1>
      <p>Please check the browser console for details.</p>
    </div>
  `;
}
//# sourceMappingURL=index.js.map