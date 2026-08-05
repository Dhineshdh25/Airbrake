import React from 'react';
export type Theme = 'dark' | 'light';
interface ThemeContextValue {
    theme: Theme;
    setTheme: (theme: Theme) => void;
}
export declare const ThemeContext: React.Context<ThemeContextValue>;
interface ThemeProviderProps {
    readonly children: React.ReactNode;
}
export declare function ThemeProvider({ children }: ThemeProviderProps): import("react/jsx-runtime").JSX.Element;
export declare function useTheme(): ThemeContextValue;
export {};
