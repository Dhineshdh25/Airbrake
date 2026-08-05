"use strict";
/**
 * Log stream filter state hook.
 * Requirements: 1.4, 1.5, 1.6
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.useLogFilters = useLogFilters;
const react_1 = require("react");
const DEFAULT_FILTERS = {
    application: '',
    environment: '',
    severity: '',
    keyword: '',
    from: '',
    to: '',
};
function useLogFilters(logs) {
    const [filters, setFilters] = (0, react_1.useState)(DEFAULT_FILTERS);
    const updateFilter = (key, value) => {
        setFilters((prev) => ({ ...prev, [key]: value }));
    };
    const resetFilters = () => setFilters(DEFAULT_FILTERS);
    const filtered = (0, react_1.useMemo)(() => {
        return logs.filter((log) => {
            if (filters.application && log.applicationId !== filters.application)
                return false;
            if (filters.environment && log.environment !== filters.environment)
                return false;
            if (filters.severity && log.severity !== filters.severity)
                return false;
            if (filters.keyword) {
                const kw = filters.keyword.toLowerCase();
                if (!log.message.toLowerCase().includes(kw))
                    return false;
            }
            if (filters.from) {
                const from = new Date(filters.from);
                if (new Date(log.timestamp) < from)
                    return false;
            }
            if (filters.to) {
                const to = new Date(filters.to);
                if (new Date(log.timestamp) > to)
                    return false;
            }
            return true;
        });
    }, [logs, filters]);
    return { filters, updateFilter, resetFilters, filtered };
}
//# sourceMappingURL=useLogFilters.js.map