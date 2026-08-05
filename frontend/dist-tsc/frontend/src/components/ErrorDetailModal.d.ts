export interface ErrorRow {
    project: string;
    file_name: string | null;
    error: string;
    error_hash?: string | null;
    error_detail?: string | null;
    timestamp: string | null;
    error_group_name?: string | null;
    error_group_id?: string | null;
    representative_id?: string | null;
}
interface StackFrame {
    file_path: string;
    line_number: number;
    function_name?: string | null;
    code_line?: string | null;
    column?: number | null;
}
interface ParsedStackTrace {
    frames: StackFrame[];
    raw_trace: string;
}
export declare function getTraceDisplayText(_errorDetail: string | null | undefined, solutionText: string | null | undefined): string | null;
export declare function getStackTraceDisplayText(errorDetail: string | null | undefined, parsedStacktrace?: ParsedStackTrace | null, aiDescription?: string | null, aiRecommendation?: string | null): string | null;
export declare function ErrorDetailModal({ row, errorHash, projectName: projectNameProp, onClose, onRefresh, }: {
    row?: ErrorRow;
    errorHash?: string;
    projectName?: string;
    onClose: () => void;
    /** Called after a resolve/reopen so the parent list can re-fetch. */
    onRefresh?: () => void;
}): import("react/jsx-runtime").JSX.Element | null;
export {};
