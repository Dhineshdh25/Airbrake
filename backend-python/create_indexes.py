"""
Create database indexes for the breaks detail endpoint optimization.

This script creates indexes that will significantly improve query performance.
Indexes are created with CONCURRENTLY to avoid table locking.
"""

import os
import sys
from db import execute, query

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TABLE = "projects_data"


def index_exists(index_name):
    """Check if an index already exists."""
    check_sql = """
        SELECT 1 FROM pg_indexes 
        WHERE tablename = %s AND indexname = %s
    """
    result = query(check_sql, (TABLE, index_name))
    return len(result) > 0


def create_index(name, sql, description):
    """Create an index if it doesn't exist."""
    print(f"\n{'='*80}")
    print(f"Index: {name}")
    print(f"{'='*80}")
    print(f"Description: {description}")
    
    if index_exists(name):
        print(f"✓ Index already exists, skipping...")
        return True
    
    print(f"Creating index...")
    print(f"SQL: {sql}")
    
    try:
        execute(sql)
        print(f"✓ Index created successfully!")
        return True
    except Exception as e:
        print(f"❌ Error creating index: {e}")
        return False


def main():
    """Create all recommended indexes."""
    print("Database Index Creation Tool")
    print("============================\n")
    print(f"Target table: {TABLE}\n")
    
    success_count = 0
    total_count = 0
    
    # Index 1: Composite index for the most common query pattern
    # This is the MOST IMPORTANT index - covers the primary query completely
    total_count += 1
    if create_index(
        "idx_projects_data_composite_error_lookup",
        f"CREATE INDEX CONCURRENTLY idx_projects_data_composite_error_lookup "
        f"ON {TABLE} (row_type, LOWER(project_name), error_hash, timestamp DESC) "
        f"WHERE row_type = 'log'",
        "Composite index covering the primary error lookup query (row_type + project + hash + timestamp)"
    ):
        success_count += 1
    
    # Index 2: Row type + error hash for log entries
    total_count += 1
    if create_index(
        "idx_projects_data_row_type_error_hash",
        f"CREATE INDEX CONCURRENTLY idx_projects_data_row_type_error_hash "
        f"ON {TABLE} (row_type, error_hash) "
        f"WHERE row_type = 'log'",
        "Speeds up error hash lookups for log entries"
    ):
        success_count += 1
    
    # Index 3: Case-insensitive project name
    total_count += 1
    if create_index(
        "idx_projects_data_project_name_lower",
        f"CREATE INDEX CONCURRENTLY idx_projects_data_project_name_lower "
        f"ON {TABLE} (LOWER(project_name))",
        "Speeds up case-insensitive project name filtering"
    ):
        success_count += 1
    
    # Index 4: Timestamp DESC for ordering
    total_count += 1
    if create_index(
        "idx_projects_data_timestamp_desc",
        f"CREATE INDEX CONCURRENTLY idx_projects_data_timestamp_desc "
        f"ON {TABLE} (timestamp DESC) "
        f"WHERE row_type = 'log'",
        "Speeds up ORDER BY timestamp DESC for log entries"
    ):
        success_count += 1
    
    # Index 5: MD5 fallback matching
    total_count += 1
    if create_index(
        "idx_projects_data_md5_error",
        f"CREATE INDEX CONCURRENTLY idx_projects_data_md5_error "
        f"ON {TABLE} (MD5(LOWER(TRIM(error)))) "
        f"WHERE row_type = 'log' AND error IS NOT NULL",
        "Speeds up fallback MD5 hash matching"
    ):
        success_count += 1
    
    # Index 6: Jira ticket lookups
    total_count += 1
    if create_index(
        "idx_projects_data_jira_ticket_hash",
        f"CREATE INDEX CONCURRENTLY idx_projects_data_jira_ticket_hash "
        f"ON {TABLE} ((metadata::jsonb->>'error_hash')) "
        f"WHERE row_type = 'jira_ticket'",
        "Speeds up Jira ticket lookups by error_hash in JSONB metadata"
    ):
        success_count += 1
    
    # Index 7: Solution lookups
    total_count += 1
    if create_index(
        "idx_projects_data_solution_lookup",
        f"CREATE INDEX CONCURRENTLY idx_projects_data_solution_lookup "
        f"ON {TABLE} (row_type, error_hash, LOWER(project_name), created_at DESC) "
        f"WHERE row_type = 'solution'",
        "Speeds up solution lookups by error_hash and project"
    ):
        success_count += 1
    
    # Index 8: Error field for non-null checks
    total_count += 1
    if create_index(
        "idx_projects_data_error_not_null",
        f"CREATE INDEX CONCURRENTLY idx_projects_data_error_not_null "
        f"ON {TABLE} (row_type) "
        f"WHERE row_type = 'log' AND error IS NOT NULL AND error <> ''",
        "Partial index for log entries with non-empty errors"
    ):
        success_count += 1
    
    print(f"\n\n{'='*80}")
    print("INDEX CREATION SUMMARY")
    print(f"{'='*80}")
    print(f"Successfully created: {success_count}/{total_count} indexes")
    
    if success_count == total_count:
        print("\n✓ All indexes created successfully!")
        print("\nNext steps:")
        print("1. Run VACUUM ANALYZE projects_data; to update table statistics")
        print("2. Test the breaks detail endpoint performance")
        print("3. Monitor query execution plans with EXPLAIN ANALYZE")
    else:
        print(f"\n⚠️  {total_count - success_count} index(es) failed to create")
        print("Review the error messages above and retry if needed")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    main()
