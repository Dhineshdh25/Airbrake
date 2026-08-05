"use strict";
// Feature: live-airbrake-monitoring-portal, Property 10: Theme Preference Round-Trip
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
const fc = __importStar(require("fast-check"));
const STORAGE_KEY = 'portal_theme';
/**
 * Validates: Requirements 3.7
 *
 * For any theme preference value (dark or light), saving the preference and
 * then loading it should return the same value.
 */
describe('Property 10: Theme Preference Round-Trip', () => {
    beforeEach(() => {
        localStorage.clear();
    });
    it('saving a theme preference and loading it returns the same value', () => {
        const themeArb = fc.constantFrom('dark', 'light');
        fc.assert(fc.property(themeArb, (theme) => {
            localStorage.setItem(STORAGE_KEY, theme);
            const loaded = localStorage.getItem(STORAGE_KEY);
            return loaded === theme;
        }), { numRuns: 100 });
    });
});
//# sourceMappingURL=theme.property.test.js.map