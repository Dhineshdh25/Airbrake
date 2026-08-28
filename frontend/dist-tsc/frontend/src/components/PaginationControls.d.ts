export declare function coercePageValue(rawValue: string, totalPages: number): number | null;
export declare function PaginationControls({ currentPage, totalPages, onPageChange, }: {
    currentPage: number;
    totalPages: number;
    onPageChange: (page: number) => void;
}): import("react/jsx-runtime").JSX.Element | null;
