interface SemanticGroupSummary {
    id?: string;
    name: string;
    value: number;
}
export declare function normalizeSemanticGroupName(row: {
    error?: string | null;
    error_group_name?: string | null;
    error_group_id?: string | null;
}): string;
export declare function summarizeSemanticGroupsForToday(rows: Array<{
    project?: string | null;
    error?: string | null;
    error_group_name?: string | null;
    error_group_id?: string | null;
}>, selectedProject?: string | null): SemanticGroupSummary[];
export declare function Dashboard(): import("react/jsx-runtime").JSX.Element;
export {};
