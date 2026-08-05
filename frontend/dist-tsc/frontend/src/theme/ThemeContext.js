"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ThemeContext = void 0;
exports.ThemeProvider = ThemeProvider;
exports.useTheme = useTheme;
const jsx_runtime_1 = require("react/jsx-runtime");
const react_1 = require("react");
const STORAGE_KEY = 'portal_theme';
exports.ThemeContext = (0, react_1.createContext)({
    theme: 'dark',
    setTheme: () => undefined,
});
function ThemeProvider({ children }) {
    const [theme, setThemeState] = (0, react_1.useState)(() => {
        const stored = localStorage.getItem(STORAGE_KEY);
        const resolved = stored === 'light' || stored === 'dark' ? stored : 'dark';
        document.documentElement.setAttribute('data-theme', resolved);
        return resolved;
    });
    const setTheme = (newTheme) => {
        localStorage.setItem(STORAGE_KEY, newTheme);
        setThemeState(newTheme);
    };
    (0, react_1.useEffect)(() => {
        localStorage.setItem(STORAGE_KEY, theme);
        document.documentElement.setAttribute('data-theme', theme);
    }, [theme]);
    const value = (0, react_1.useMemo)(() => ({ theme, setTheme }), [theme]);
    return ((0, jsx_runtime_1.jsx)(exports.ThemeContext.Provider, { value: value, children: children }));
}
function useTheme() {
    return (0, react_1.useContext)(exports.ThemeContext);
}
//# sourceMappingURL=ThemeContext.js.map