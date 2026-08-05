"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.getSafeUUID = getSafeUUID;
function getSafeUUID() {
    return (globalThis.crypto?.randomUUID?.() ??
        `${Date.now()}-${Math.random().toString(36).slice(2)}`);
}
//# sourceMappingURL=uuid.js.map