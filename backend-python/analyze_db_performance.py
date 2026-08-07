"""
Database performance analysis script for breaks detail endpoint.

This script helps identify:
1. Missing indexes
2. Sequential scans in queries
3. Query execution times with EXPLAIN ANALYZE
"""

import os
import sys
from db import query

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TABLE = "projects_data"


def check_indexes():
    """List all indexes on the projects_data table."""
    print("\n" + "="*80)
    print("EXISTING INDEXES")
    print("="*80)
    
    index_query = """
        SELECT 
            indexname,
            indexdef
        FROM pg_indexes
        WHERE tablename = %s
        ORDER BY indexname;
    """
    
    try:
        indexes = query(index_query, (TABLE,))
        if not indexes:
            print("⚠️  NO INDEXES FOUND ON projects_data TABLE!")
        else:
            for idx in indexes:
                print(f"\n{idx['indexname']}:")
                print(f"  {idx['indexdef']}")
    except Exception as e:
        print(f"❌ Error checking indexes: {e}")


def analyze_query(sql, params, description):
    """Run EXPLAIN ANALYZE on a query."""
    print("\n" + "="*80)
    print(f"QUERY ANALYSIS: {description}")
    print("="*80)
    print(f"\nQuery:\n{sql}")
    print(f"\nParams: {params}")
    
    explain_sql = f"EXPLAIN ANALYZE {sql}"
    
    try:
        results = query(explain_sql, params)
        print("\n--- EXPLAIN ANALYZE Results ---")
        for row in results:
            print(row.get('QUERY PLAN', ''))
    except Exception as e:
        print(f"❌ Error running EXPLAIN ANALYZE: {e}")


def suggest_indexes():
    """Suggest indexes based on common query patterns."""
    print("\n" + "="*80)
    print("RECOMMENDED INDEXES")
    print("="*80)
    
    recommendations = [
        {
            "name": "idx_projects_data_row_type_error_hash",
            "sql": f"CREATE INDEX CONCURRENTLY idx_projects_data_row_type_error_hash ON {TABLE} (row_type, error_hash) WHERE row_type = 'log';",
            "reason": "Speeds up error hash lookups for log entries (primary query pattern)"
        },
        {
            "name": "idx_projects_data_project_name_lower",
            "sql": f"CREATE INDEX CONCURRENTLY idx_projects_data_project_name_lower ON {TABLE} (LOWER(project_name));",
            "reason": "Speeds up case-insensitive project name filtering"
        },
        {
            "name": "idx_projects_data_timestamp_desc",
            "sql": f"CREATE INDEX CONCURRENTLY idx_projects_data_timestamp_desc ON {TABLE} (timestamp DESC) WHERE row_type = 'log';",
            "reason": "Speeds up ORDER BY timestamp DESC for log entries"
        },
        {
            "name": "idx_projects_data_md5_error",
            "sql": f"CREATE INDEX CONCURRENTLY idx_projects_data_md5_error ON {TABLE} (MD5(LOWER(TRIM(error)))) WHERE row_type = 'log' AND error IS NOT NULL;",
            "reason": "Speeds up fallback MD5 hash matching"
        },
        {
            "name": "idx_projects_data_jira_ticket",
            "sql": f"CREATE INDEX CONCURRENTLY idx_projects_data_jira_ticket ON {TABLE} ((metadata::jsonb->>'error_hash')) WHERE row_type = 'jira_ticket';",
            "reason": "Speeds up Jira ticket lookups by error_hash"
        },
        {
            "name": "idx_projects_data_solution_hash",
            "sql": f"CREATE INDEX CONCURRENTLY idx_projects_data_solution_hash ON {TABLE} (row_type, error_hash, project_name) WHERE row_type = 'solution';",
            "reason": "Speeds up solution lookups by error_hash and project"
        },
        {
            "name": "idx_projects_data_composite_error_lookup",
            "sql": f"CREATE INDEX CONCURRENTLY idx_projects_data_composite_error_lookup ON {TABLE} (row_type, LOWER(project_name), error_hash, timestamp DESC) WHERE row_type = 'log';",
            "reason": "Composite index for the most common query pattern (covers primary query completely)"
        },
    ]
    
    for rec in recommendations:
        print(f"\n{rec['name']}:")
        print(f"  Reason: {rec['reason']}")
        print(f"  SQL: {rec['sql']}")


def main():
    """Main analysis function."""
    print("Database Performance Analysis Tool")
    print("==================================\n")
    
    # Check existing indexes
    check_indexes()
    
    # Analyze common query patterns
    print("\n\n" + "="*80)
    print("QUERY PERFORMANCE ANALYSIS")
    print("="*80)
    
    # Example error_hash and project for testing
    test_error_hash = "ba92a948b9e7446f3b3da2e14eb46269"  # Use a real one from your DB
    test_project = "ScholarFinder"  # Use a real one from your DB
    
    # Query 1: Primary query (most common)
    primary_sql = f"""
        SELECT id, project_name, error AS error_message, error_detail, error_hash, 
        failure_count, timestamp, error_status, reopened_at, file_name, 
        error_group_name 
        FROM {TABLE} 
        WHERE row_type = 'log' 
        AND error IS NOT NULL 
        AND error <> '' 
        AND error_hash = %s 
        AND LOWER(project_name) = LOWER(%s) 
        ORDER BY timestamp DESC
    """
    analyze_query(primary_sql, (test_error_hash, test_project), "Primary Error Lookup")
    
    # Query 2: Jira ticket lookup
    jira_sql = f"""
        SELECT metadata 
        FROM {TABLE} 
        WHERE row_type = 'jira_ticket' 
        AND metadata::jsonb->>'error_hash' = %s 
        AND LOWER(metadata::jsonb->>'project_name') = LOWER(%s) 
        ORDER BY created_at DESC 
        LIMIT 1
    """
    analyze_query(jira_sql, (test_error_hash, test_project), "Jira Ticket Lookup")
    
    # Query 3: Solution lookup
    solution_sql = f"""
        SELECT id, solution, created_at, created_by, version, confidence_score, usage_count 
        FROM {TABLE} 
        WHERE row_type = 'solution' 
        AND error_hash = %s 
        AND LOWER(project_name) = LOWER(%s) 
        ORDER BY created_at DESC 
        LIMIT 1
    """
    analyze_query(solution_sql, (test_error_hash, test_project), "Solution Lookup")
    
    # Suggest indexes
    suggest_indexes()
    
    print("\n\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    print("\nNext steps:")
    print("1. Review the EXPLAIN ANALYZE output for 'Seq Scan' entries")
    print("2. Apply the recommended indexes using the SQL commands above")
    print("3. Use CONCURRENTLY to avoid locking the table during index creation")
    print("4. Monitor query performance after index creation")
    print("5. Run VACUUM ANALYZE after creating indexes")


if __name__ == "__main__":
    main()
