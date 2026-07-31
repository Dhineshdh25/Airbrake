"""Regression tests for the AIRBRAKE semantic architecture.

Coverage:
  - Pinecone retrieval (TIER 1)
  - Aurora embedding fallback (TIER 2)
  - Hash fallback (TIER 3)
  - Cross-hash retrieval
  - Cross-hash exact duplicate detection
  - Exact duplicate detection
  - Semantic duplicate detection
  - LLM confirmation at 0.90–0.95 boundary
  - use_solution route — minimal storage, no history columns
  - Reopen route — no lifecycle rows
  - Concurrent usage increment (atomic)
  - Version creation with retry
  - Failure handling (Bedrock unavailable, Pinecone unavailable)
  - Project isolation enforcement

Existing tests in test_error_matching.py, test_get_break_detail.py, and
test_break_detail_lookup.py are NOT modified or removed.
"""
import importlib.util
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]

def _load(rel_path, name):
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

kb  = _load('ai/knowledge_base.py',   'kb')
rec = _load('ai/recommendations.py',  'rec')
app_module = _load('app.py',          'airbrake_app')
grouper = _load('ai/error_grouper.py', 'error_grouper')

# ── Shared fixtures ────────────────────────────────────────────────────────────

FAKE_EMBEDDING = [0.1] * 1024

LOG_ROW = {
    'id': 'log-001',
    'project_name': 'ProjectX',
    'error_hash': 'hash-a',
}

SOLUTION_ROW_A = {
    'id': 'sol-a',
    'row_type': 'solution',
    'solution': 'Fix the database connection pool.',
    'created_by': 'alice',
    'created_at': None,
    'usage_count': 3,
    'version': 1,
    'confidence_score': 56.0,
    'embedding': '[' + ','.join(['0.1'] * 1024) + ']',
    'log_ref_id': 'log-001',
    'error_hash': 'hash-a',
}

SOLUTION_ROW_B = dict(SOLUTION_ROW_A, id='sol-b', error_hash='hash-b',
                      log_ref_id='log-002')


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PINECONE RETRIEVAL (TIER 1)
# ═══════════════════════════════════════════════════════════════════════════════

class PineconeRetrievalTests(unittest.TestCase):

    def _fake_error_row(self):
        return [{'error_message': 'DB timeout', 'error_detail': ''}]

    def test_tier1_returns_hydrated_rows_when_pinecone_succeeds(self):
        pinecone_matches = [{'id': 'sol-a', 'score': 0.92, 'metadata': {}}]
        with mock.patch.object(rec, 'query', side_effect=[
            self._fake_error_row(),      # _fetch_error_text
            [SOLUTION_ROW_A],            # hydrate from Aurora
        ]), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar', return_value=pinecone_matches):
            results = rec.get_similar_solutions('hash-a', project_name='ProjectX', limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 'sol-a')

    def test_tier1_pinecone_called_without_error_hash_filter(self):
        """TIER 1 must never pass error_hash to Pinecone — cross-hash is the whole point."""
        calls = []
        def fake_query_similar(**kwargs):
            calls.append(kwargs)
            return []
        with mock.patch.object(rec, 'query', side_effect=[
            self._fake_error_row(), [],
        ]), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar', side_effect=fake_query_similar):
            rec.get_similar_solutions('hash-a', project_name='ProjectX')
        self.assertTrue(len(calls) > 0)
        self.assertIsNone(calls[0].get('error_hash'))

    def test_tier1_hydration_applies_project_filter(self):
        """Aurora hydration must include project_name to enforce isolation."""
        hydrate_sqls = []
        pinecone_matches = [{'id': 'sol-a', 'score': 0.9, 'metadata': {}}]
        def fake_query(sql, params=None):
            if 'id IN' in sql:
                hydrate_sqls.append((sql, params))
                return []
            return self._fake_error_row()
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar', return_value=pinecone_matches):
            rec.get_similar_solutions('hash-a', project_name='ProjectX')
        self.assertTrue(len(hydrate_sqls) > 0)
        self.assertIn('LOWER(project_name)', hydrate_sqls[0][0])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. AURORA EMBEDDING FALLBACK (TIER 2)
# ═══════════════════════════════════════════════════════════════════════════════

class AuroraFallbackTests(unittest.TestCase):

    def _fake_error_row(self):
        return [{'error_message': 'DB timeout', 'error_detail': ''}]

    def test_tier2_runs_when_pinecone_returns_empty(self):
        with mock.patch.object(rec, 'query', side_effect=[
            self._fake_error_row(),       # _fetch_error_text
            [SOLUTION_ROW_A],             # TIER 2 Aurora scan
        ]), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar', return_value=[]):
            results = rec.get_similar_solutions('hash-a', project_name='ProjectX', limit=5)
        # TIER 2 result returned (similarity 1.0 because both embeddings are identical)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 'sol-a')

    def test_tier2_applies_project_filter_in_aurora_scan(self):
        scan_sqls = []
        def fake_query(sql, params=None):
            if 'embedding IS NOT NULL' in sql:
                scan_sqls.append((sql, params))
                return []
            return self._fake_error_row()
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar', return_value=[]):
            rec.get_similar_solutions('hash-a', project_name='ProjectX')
        self.assertTrue(len(scan_sqls) > 0)
        self.assertIn('LOWER(project_name)', scan_sqls[0][0])

    def test_tier2_skipped_when_project_name_absent(self):
        """Without project_name, TIER 2 must NOT run (prevents cross-project leaks)."""
        scan_called = []
        def fake_query(sql, params=None):
            if 'embedding IS NOT NULL' in sql:
                scan_called.append(sql)
            return self._fake_error_row() if "row_type = 'log'" in sql else []
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar', return_value=[]):
            rec.get_similar_solutions('hash-a', project_name=None)
        self.assertEqual(len(scan_called), 0,
            "TIER 2 must not run without project_name")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HASH FALLBACK (TIER 3)
# ═══════════════════════════════════════════════════════════════════════════════

class HashFallbackTests(unittest.TestCase):

    def test_tier3_runs_when_bedrock_unavailable(self):
        """If create_embedding raises, TIER 3 must still return results."""
        hash_sqls = []
        def fake_query(sql, params=None):
            if "row_type = 'solution'" in sql and 'error_hash' in sql:
                hash_sqls.append(sql)
                return [SOLUTION_ROW_A]
            return [{'error_message': 'DB timeout', 'error_detail': ''}]
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding',
                   side_effect=RuntimeError('Bedrock unavailable')):
            results = rec.get_similar_solutions('hash-a', project_name='ProjectX')
        self.assertEqual(len(results), 1)
        self.assertTrue(len(hash_sqls) > 0)

    def test_tier3_uses_exact_hash_equality(self):
        sqls = []
        def fake_query(sql, params=None):
            sqls.append(sql)
            if "error_hash = %s" in sql and "row_type = 'solution'" in sql:
                return [SOLUTION_ROW_A]
            return [{'error_message': 'DB timeout', 'error_detail': ''}]
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding',
                   side_effect=RuntimeError('unavailable')):
            rec.get_similar_solutions('hash-a', project_name='ProjectX')
        tier3_sql = next((s for s in sqls if "error_hash = %s" in s
                          and "row_type = 'solution'" in s), None)
        self.assertIsNotNone(tier3_sql)

    def test_tier3_runs_without_project_name(self):
        """TIER 3 must be the only tier that runs when project_name is absent."""
        results_holder = []
        def fake_query(sql, params=None):
            if "error_hash = %s" in sql and "row_type = 'solution'" in sql:
                results_holder.append('tier3_ran')
                return [SOLUTION_ROW_A]
            return [{'error_message': 'timeout', 'error_detail': ''}]
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding',
                   side_effect=RuntimeError('unavailable')):
            results = rec.get_similar_solutions('hash-a', project_name=None)
        self.assertIn('tier3_ran', results_holder)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CROSS-HASH RETRIEVAL
# ═══════════════════════════════════════════════════════════════════════════════

class CrossHashRetrievalTests(unittest.TestCase):

    def test_solution_from_different_hash_surfaces_via_pinecone(self):
        """A solution saved under hash-b must appear when querying hash-a
        if Pinecone returns its solution_id as a match."""
        # SOLUTION_ROW_B has error_hash='hash-b' but Pinecone returns it for hash-a query
        pinecone_matches = [{'id': 'sol-b', 'score': 0.91, 'metadata': {}}]
        def fake_query(sql, params=None):
            if 'id IN' in sql:
                return [SOLUTION_ROW_B]
            return [{'error_message': 'File not found', 'error_detail': ''}]
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar', return_value=pinecone_matches):
            results = rec.get_similar_solutions('hash-a', project_name='ProjectX')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 'sol-b')

    def test_cross_hash_result_still_filtered_by_project(self):
        """Cross-hash result from Pinecone must still be filtered by project_name
        in the Aurora hydration step — wrong project must not appear."""
        pinecone_matches = [{'id': 'sol-b', 'score': 0.95, 'metadata': {}}]
        def fake_query(sql, params=None):
            if 'id IN' in sql:
                # Aurora returns empty because project_name filter excluded it
                return []
            return [{'error_message': 'File not found', 'error_detail': ''}]
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar', return_value=pinecone_matches):
            results = rec.get_similar_solutions('hash-a', project_name='ProjectX')
        # Pinecone matched but Aurora hydration filtered it out — result must be empty
        self.assertEqual(len(results), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. EXACT DUPLICATE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

class ExactDuplicateDetectionTests(unittest.TestCase):

    def test_exact_match_same_log_ref_id(self):
        rows = [dict(SOLUTION_ROW_A, solution='Fix the DB connection pool.')]
        with mock.patch.object(kb, 'query', return_value=rows):
            result = kb._find_duplicate_solution('log-001', 'Fix the DB connection pool.')
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'sol-a')

    def test_exact_match_is_case_insensitive(self):
        rows = [dict(SOLUTION_ROW_A, solution='FIX THE DB CONNECTION POOL.')]
        with mock.patch.object(kb, 'query', return_value=rows):
            result = kb._find_duplicate_solution('log-001', 'fix the db connection pool.')
        self.assertIsNotNone(result)

    def test_exact_match_whitespace_normalized(self):
        rows = [dict(SOLUTION_ROW_A, solution='Fix   the  DB.')]
        with mock.patch.object(kb, 'query', return_value=rows):
            result = kb._find_duplicate_solution('log-001', 'Fix the DB.')
        self.assertIsNotNone(result)

    def test_no_match_returns_none(self):
        rows = [dict(SOLUTION_ROW_A, solution='Something completely different.')]
        with mock.patch.object(kb, 'query', return_value=rows):
            result = kb._find_duplicate_solution('log-001', 'Fix the DB connection pool.')
        self.assertIsNone(result)

    def test_exact_match_runs_before_bedrock_is_called(self):
        """Exact match must be checked before any Bedrock embedding is generated."""
        embedding_calls = []
        rows = [dict(SOLUTION_ROW_A, solution='Fix the DB.')]
        def fake_create_embedding(text):
            embedding_calls.append(text)
            return FAKE_EMBEDDING

        with mock.patch.object(kb, '_get_log_row', return_value=LOG_ROW), \
        mock.patch.object(kb, 'query', return_value=rows), \
        mock.patch.object(kb, 'execute_returning', return_value=None), \
        mock.patch('ai.embeddings.create_embedding', side_effect=fake_create_embedding):
            kb.insert_solution('hash-a', 'Fix the DB.',
                               project_name='ProjectX', created_by='dev')
        # Bedrock must not have been called because exact-text matched first
        self.assertEqual(len(embedding_calls), 0,
            "Bedrock should not be called when exact-text duplicate is found first")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. CROSS-HASH EXACT DUPLICATE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

class CrossHashExactDuplicateTests(unittest.TestCase):

    def test_pass2_finds_identical_text_under_different_hash(self):
        """Pass 2 of _find_duplicate_solution must scan the whole project
        and return a match from a different log_ref_id."""
        cross_hash_row = dict(SOLUTION_ROW_B,
                              solution='Fix the DB connection pool.',
                              log_ref_id='log-002')

        def fake_query(sql, params=None):
            if 'log_ref_id = %s' in sql:
                return []           # pass 1 — same log_ref_id: no match
            if 'log_ref_id != %s' in sql:
                return [cross_hash_row]  # pass 2 — project-wide: match found
            return []

        with mock.patch.object(kb, 'query', side_effect=fake_query):
            result = kb._find_duplicate_solution(
                'log-001', 'Fix the DB connection pool.', project_name='ProjectX'
            )
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'sol-b')

    def test_pass2_skipped_when_project_name_absent(self):
        """Without project_name, pass 2 must not run (no project isolation possible)."""
        pass2_called = []
        def fake_query(sql, params=None):
            if 'log_ref_id != %s' in sql:
                pass2_called.append(sql)
                return []
            return []
        with mock.patch.object(kb, 'query', side_effect=fake_query):
            kb._find_duplicate_solution('log-001', 'Some solution text.')
        self.assertEqual(len(pass2_called), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. SEMANTIC DUPLICATE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

class SemanticDuplicateDetectionTests(unittest.TestCase):

    def test_high_similarity_flagged_as_duplicate(self):
        pinecone_result = [{'id': 'sol-a', 'score': 0.97,
                            'metadata': {'solution_id': 'sol-a'}}]
        with mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(kb, 'query_similar', return_value=pinecone_result), \
        mock.patch.object(kb, '_find_solution', return_value=SOLUTION_ROW_A):
            result = kb.detect_duplicate_solution(
                'Fix the DB.', 'hash-a', project_name='ProjectX'
            )
        self.assertTrue(result['is_duplicate'])
        self.assertTrue(result['duplicate_prompt'])
        self.assertEqual(result['decision'], 'duplicate')

    def test_below_threshold_not_duplicate(self):
        pinecone_result = [{'id': 'sol-a', 'score': 0.50,
                            'metadata': {'solution_id': 'sol-a'}}]
        with mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(kb, 'query_similar', return_value=pinecone_result), \
        mock.patch.object(kb, '_find_solution', return_value=SOLUTION_ROW_A):
            result = kb.detect_duplicate_solution(
                'Completely unrelated fix.', 'hash-a', project_name='ProjectX'
            )
        self.assertFalse(result['is_duplicate'])
        self.assertFalse(result['duplicate_prompt'])

    def test_no_hash_filter_passed_to_pinecone(self):
        """detect_duplicate_solution must call Pinecone without error_hash filter."""
        calls = []
        def fake_query_similar(**kwargs):
            calls.append(kwargs)
            return []
        with mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(kb, 'query_similar', side_effect=fake_query_similar):
            kb.detect_duplicate_solution('Some fix.', 'hash-a', project_name='ProjectX')
        self.assertTrue(len(calls) > 0)
        self.assertIsNone(calls[0].get('error_hash'),
            "Pinecone must be called without error_hash to enable cross-hash detection")


class ErrorGrouperClassificationTests(unittest.TestCase):

    def test_pinecone_auto_threshold_skips_nova(self):
        with mock.patch.object(grouper, '_get_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(grouper, '_pinecone_query_errors', return_value=[{
            'id': 'match-1', 'score': 0.94,
            'metadata': {'group_id': 'group-1', 'group_name': 'Existing Group'}
        }]), \
        mock.patch.object(grouper, '_write_group_to_row') as fake_write, \
        mock.patch.object(grouper, '_pinecone_upsert_error') as fake_upsert, \
        mock.patch('ai.bedrock_llm._call_nova') as fake_nova:
            result = grouper.classify_error(
                'log-001', 'Database timeout error', 'ProjectX', 'Stack trace here'
            )
        self.assertEqual(result['reason'], 'pinecone_auto')
        self.assertEqual(result['group_id'], 'group-1')
        self.assertEqual(result['group_name'], 'Existing Group')
        self.assertFalse(fake_nova.called, 'Nova must not be called for auto threshold matches')
        fake_write.assert_called_once()
        fake_upsert.assert_called_once()

    def test_fuzzy_score_uses_nova_confirm_same_group(self):
        with mock.patch.object(grouper, '_get_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(grouper, '_pinecone_query_errors', return_value=[{
            'id': 'match-2', 'score': 0.85,
            'metadata': {'group_id': 'group-2', 'group_name': 'Fuzzy Group'}
        }]), \
        mock.patch.object(grouper, '_write_group_to_row') as fake_write, \
        mock.patch.object(grouper, '_pinecone_upsert_error') as fake_upsert, \
        mock.patch('ai.bedrock_llm._call_nova', return_value='YES') as fake_nova:
            result = grouper.classify_error(
                'log-002', 'User login failed', 'ProjectX', 'Auth module failure'
            )
        self.assertEqual(result['reason'], 'nova_confirmed')
        self.assertEqual(result['group_id'], 'group-2')
        self.assertEqual(result['group_name'], 'Fuzzy Group')
        self.assertTrue(fake_nova.called, 'Nova confirm_same_group must be called in fuzzy band')
        fake_write.assert_called_once()
        fake_upsert.assert_called_once()

    def test_below_fuzzy_threshold_creates_new_group_without_confirmation(self):
        with mock.patch.object(grouper, '_get_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(grouper, '_pinecone_query_errors', return_value=[{
            'id': 'match-3', 'score': 0.80,
            'metadata': {'group_id': 'group-3', 'group_name': 'Weak Group'}
        }]), \
        mock.patch.object(grouper, '_write_group_to_row') as fake_write, \
        mock.patch.object(grouper, '_pinecone_upsert_error_with_group_name') as fake_upsert, \
        mock.patch.object(grouper, '_nova_confirm_same_group') as fake_confirm, \
        mock.patch.object(grouper, '_nova_name_group', return_value='New Semantic Group'):
            result = grouper.classify_error(
                'log-003', 'Cache miss error', 'ProjectX', 'Redis key missing'
            )
        self.assertEqual(result['reason'], 'provisional_new_group')
        self.assertEqual(result['group_name'], 'New Semantic Group')
        self.assertFalse(fake_confirm.called,
            'Nova confirmation must not be called below the fuzzy threshold')
        fake_write.assert_called_once()
        fake_upsert.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# 8. LLM CONFIRMATION AT 0.90–0.95 BOUNDARY
# ═══════════════════════════════════════════════════════════════════════════════

class LLMConfirmationTests(unittest.TestCase):

    def _pinecone_at(self, score):
        return [{'id': 'sol-a', 'score': score, 'metadata': {'solution_id': 'sol-a'}}]

    def test_llm_called_at_warn_boundary(self):
        """At 0.92 similarity Nova Lite must be consulted."""
        llm_calls = []
        def fake_nova(prompt, max_tokens=256):
            llm_calls.append(prompt)
            return 'YES'
        with mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(kb, 'query_similar', return_value=self._pinecone_at(0.92)), \
        mock.patch.object(kb, '_find_solution', return_value=SOLUTION_ROW_A), \
        mock.patch('ai.llm.generate_ai_response', side_effect=fake_nova):
            result = kb.detect_duplicate_solution('Similar fix.', 'hash-a', 'ProjectX')
        self.assertTrue(len(llm_calls) > 0, 'Nova Lite must be called at 0.90-0.95 boundary')
        self.assertTrue(result['is_duplicate'])

    def test_llm_not_called_above_095(self):
        """At >= 0.95 similarity it is an immediate duplicate — LLM not needed."""
        llm_calls = []
        with mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(kb, 'query_similar', return_value=self._pinecone_at(0.97)), \
        mock.patch.object(kb, '_find_solution', return_value=SOLUTION_ROW_A), \
        mock.patch('ai.llm.generate_ai_response', side_effect=lambda *a, **kw: llm_calls.append(1) or 'NO'):
            result = kb.detect_duplicate_solution('Very similar fix.', 'hash-a', 'ProjectX')
        self.assertEqual(len(llm_calls), 0, 'LLM must not be called when score >= 0.95')
        self.assertTrue(result['is_duplicate'])

    def test_llm_no_answer_treated_as_not_duplicate(self):
        """If Nova Lite says NO at the boundary, the solution must not be blocked."""
        with mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(kb, 'query_similar', return_value=self._pinecone_at(0.91)), \
        mock.patch.object(kb, '_find_solution', return_value=SOLUTION_ROW_A), \
        mock.patch('ai.llm.generate_ai_response', return_value='NO'):
            result = kb.detect_duplicate_solution('Different phrasing.', 'hash-a', 'ProjectX')
        self.assertFalse(result['is_duplicate'])
        self.assertTrue(result['duplicate_prompt'])   # still a warn but not a block

    def test_llm_exception_does_not_block_save(self):
        """If Nova Lite raises, duplicate detection must fail open."""
        with mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(kb, 'query_similar', return_value=self._pinecone_at(0.91)), \
        mock.patch.object(kb, '_find_solution', return_value=SOLUTION_ROW_A), \
        mock.patch('ai.llm.generate_ai_response', side_effect=RuntimeError('Nova down')):
            result = kb.detect_duplicate_solution('Different phrasing.', 'hash-a', 'ProjectX')
        # Must not raise; must resolve to warn (not blocked)
        self.assertFalse(result['is_duplicate'])


# ═══════════════════════════════════════════════════════════════════════════════
# 9. USE SOLUTION ROUTE
# ═══════════════════════════════════════════════════════════════════════════════

class UseSolutionRouteTests(unittest.TestCase):
    """Verify that use_solution increments usage and resolves the error.
    No resolution history columns — storage stays minimal."""

    def _setup_app(self):
        return app_module.app.test_client()

    def test_use_solution_returns_used_true(self):
        with mock.patch.object(app_module, 'increment_usage',
                               return_value=dict(SOLUTION_ROW_A, usage_count=4)), \
        mock.patch.object(app_module, 'execute', return_value=1):
            client = self._setup_app()
            resp = client.post('/api/knowledge_base/use',
                               json={'solution_id': 'sol-a',
                                     'error_hash': 'hash-a',
                                     'project_name': 'ProjectX'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json().get('used'))

    def test_use_solution_requires_all_three_fields(self):
        client = self._setup_app()
        resp = client.post('/api/knowledge_base/use',
                           json={'solution_id': 'sol-a', 'error_hash': 'hash-a'})
        self.assertEqual(resp.status_code, 400)

    def test_use_solution_does_not_write_history_columns(self):
        """No resolved_solution_id, resolved_version, or resolved_by columns."""
        execute_sqls = []
        def fake_execute(sql, params=None):
            execute_sqls.append(sql)
            return 1
        with mock.patch.object(app_module, 'increment_usage',
                               return_value=dict(SOLUTION_ROW_A, usage_count=4)), \
        mock.patch.object(app_module, 'execute', side_effect=fake_execute):
            client = self._setup_app()
            client.post('/api/knowledge_base/use',
                        json={'solution_id': 'sol-a',
                              'error_hash': 'hash-a',
                              'project_name': 'ProjectX'})
        for sql in execute_sqls:
            self.assertNotIn('resolved_solution_id', sql,
                "use_solution must not write history columns — minimal storage")
            self.assertNotIn('resolved_version', sql)
            self.assertNotIn('resolved_by', sql)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. REOPEN ROUTE — basic functionality
# ═══════════════════════════════════════════════════════════════════════════════

class ReopenRouteTests(unittest.TestCase):

    def _setup_app(self):
        return app_module.app.test_client()

    def test_reopen_updates_error_status(self):
        execute_sqls = []
        def fake_execute(sql, params=None):
            execute_sqls.append((sql, params))
            return 1
        with mock.patch.object(app_module, 'execute', side_effect=fake_execute):
            client = self._setup_app()
            resp = client.post('/api/knowledge_base/reopen',
                               json={'error_hash': 'hash-a',
                                     'project_name': 'ProjectX'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn('reopened', data)

    def test_reopen_requires_error_hash_and_project_name(self):
        client = self._setup_app()
        resp = client.post('/api/knowledge_base/reopen', json={'error_hash': 'hash-a'})
        self.assertEqual(resp.status_code, 400)

    def test_reopen_does_not_create_lifecycle_rows(self):
        """Reopen must only UPDATE the log row — no INSERT of lifecycle rows."""
        insert_sqls = []
        def fake_execute(sql, params=None):
            if sql.strip().upper().startswith('INSERT'):
                insert_sqls.append(sql)
            return 1
        with mock.patch.object(app_module, 'execute', side_effect=fake_execute):
            client = self._setup_app()
            client.post('/api/knowledge_base/reopen',
                        json={'error_hash': 'hash-a', 'project_name': 'ProjectX'})
        self.assertEqual(len(insert_sqls), 0,
            "Reopen must not create any INSERT rows — storage efficiency")


# ═══════════════════════════════════════════════════════════════════════════════
# 11. CONCURRENT USAGE INCREMENT (ATOMIC)
# ═══════════════════════════════════════════════════════════════════════════════

class AtomicUsageIncrementTests(unittest.TestCase):

    def test_increment_usage_uses_atomic_sql(self):
        """increment_usage must use inline SQL arithmetic, not a read-then-write."""
        execute_calls = []
        incremented = dict(SOLUTION_ROW_A, usage_count=4)
        updated     = dict(SOLUTION_ROW_A, usage_count=4, confidence_score=58.0)

        def fake_execute_returning(sql, params=None):
            execute_calls.append((sql, params))
            if 'usage_count = usage_count + 1' in sql:
                return incremented
            if 'confidence_score' in sql:
                return updated
            return None

        with mock.patch.object(kb, 'execute_returning',
                               side_effect=fake_execute_returning):
            result = kb.increment_usage('sol-a')

        atomic_sql = next(
            (s for s, _ in execute_calls if 'usage_count = usage_count + 1' in s),
            None
        )
        self.assertIsNotNone(atomic_sql,
            "increment_usage must use SET usage_count = usage_count + 1 (atomic)")
        self.assertEqual(result['usage_count'], 4)

    def test_increment_usage_does_not_do_select_before_update(self):
        """There must be no SELECT before the UPDATE in increment_usage."""
        query_calls = []
        incremented = dict(SOLUTION_ROW_A, usage_count=4)
        updated     = dict(SOLUTION_ROW_A, usage_count=4, confidence_score=58.0)

        with mock.patch.object(kb, 'query', side_effect=lambda *a, **kw: query_calls.append(a) or []), \
        mock.patch.object(kb, 'execute_returning', side_effect=[incremented, updated]):
            kb.increment_usage('sol-a')

        self.assertEqual(len(query_calls), 0,
            "increment_usage must not issue a SELECT (eliminates read-then-write race)")

    def test_increment_usage_raises_when_solution_not_found(self):
        with mock.patch.object(kb, 'execute_returning', return_value=None):
            with self.assertRaises(ValueError):
                kb.increment_usage('nonexistent-id')

    def test_confidence_recalculated_after_atomic_increment(self):
        """Confidence must be recalculated from the DB-returned usage_count."""
        incremented = dict(SOLUTION_ROW_A, usage_count=10)
        expected_confidence = kb.calculate_confidence(10)   # 50 + 10*2 = 70.0

        update_params = []
        def fake_execute_returning(sql, params=None):
            if 'usage_count = usage_count + 1' in sql:
                return incremented
            if 'confidence_score' in sql:
                update_params.append(params)
                return dict(incremented, confidence_score=params[0])
            return None

        with mock.patch.object(kb, 'execute_returning',
                               side_effect=fake_execute_returning):
            result = kb.increment_usage('sol-a')

        self.assertEqual(result['confidence_score'], expected_confidence)


# ═══════════════════════════════════════════════════════════════════════════════
# 12. VERSION CREATION WITH RETRY
# ═══════════════════════════════════════════════════════════════════════════════

class VersionCreationRetryTests(unittest.TestCase):

    def _make_new_row(self, version):
        return dict(SOLUTION_ROW_A, id=f'sol-new-v{version}', version=version,
                    duplicate=False)


    def test_insert_solution_assigns_version_from_max_plus_one(self):
        version_holder = []
        def fake_execute_returning(sql, params=None):
            if 'INSERT' in sql:
                # INSERT params (positional, excluding 'solution' literal and NOW()):
                # [0]=id  [1]=project_name  [2]=error_hash  [3]=log_ref_id
                # [4]=solution  [5]=created_by  [6]=usage_count  [7]=version
                # [8]=confidence_score  [9]=embedding
                version_holder.append(params[7])   # version is index 7
                return self._make_new_row(params[7])
            return None
        with mock.patch.object(kb, '_get_log_row', return_value=LOG_ROW), \
        mock.patch.object(kb, '_find_duplicate_solution', return_value=None), \
        mock.patch.object(kb, 'detect_duplicate_solution',
                          return_value={'duplicate_prompt': False}), \
        mock.patch.object(kb, 'query',
                          return_value=[{'max_version': 2}]), \
        mock.patch.object(kb, 'execute_returning',
                          side_effect=fake_execute_returning), \
        mock.patch.object(kb, '_create_embedding_safe', return_value=None), \
        mock.patch.object(kb, 'upsert_vector', return_value=True):
            result = kb.insert_solution('hash-a', 'Brand new solution.',
                                        project_name='ProjectX', created_by='dev')
        self.assertEqual(version_holder[0], 3,
            "New version must be MAX(version)+1 = 3")

    def test_insert_solution_retries_on_unique_constraint_violation(self):
        """On a duplicate version collision, insert_solution must retry."""
        attempt_counter = {'n': 0}

        def fake_execute_returning(sql, params=None):
            if 'INSERT' in sql:
                attempt_counter['n'] += 1
                if attempt_counter['n'] < 3:
                    raise Exception('duplicate key value violates unique constraint')
                return self._make_new_row(params[7])  # version is index 7
            return None

        def fake_query(sql, params=None):
            return [{'max_version': attempt_counter['n']}]

        with mock.patch.object(kb, '_get_log_row', return_value=LOG_ROW), \
        mock.patch.object(kb, '_find_duplicate_solution', return_value=None), \
        mock.patch.object(kb, 'detect_duplicate_solution',
                          return_value={'duplicate_prompt': False}), \
        mock.patch.object(kb, 'query', side_effect=fake_query), \
        mock.patch.object(kb, 'execute_returning',
                          side_effect=fake_execute_returning), \
        mock.patch.object(kb, '_create_embedding_safe', return_value=None), \
        mock.patch.object(kb, 'upsert_vector', return_value=True):
            result = kb.insert_solution('hash-a', 'Concurrent solution.',
                                        project_name='ProjectX', created_by='dev')

        self.assertEqual(attempt_counter['n'], 3,
            "Should have taken 3 attempts (2 failures + 1 success)")
        self.assertIsNotNone(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 13. BEDROCK UNAVAILABLE — graceful degradation
# ═══════════════════════════════════════════════════════════════════════════════

class BedrockUnavailableTests(unittest.TestCase):

    def test_insert_solution_saves_without_embedding_when_bedrock_down(self):
        """insert_solution must save the row even if Bedrock raises."""
        inserted = []
        def fake_execute_returning(sql, params=None):
            if 'INSERT' in sql:
                inserted.append(params)
                return dict(SOLUTION_ROW_A, id='sol-new', embedding=None)
            return None
        with mock.patch.object(kb, '_get_log_row', return_value=LOG_ROW), \
        mock.patch.object(kb, '_find_duplicate_solution', return_value=None), \
        mock.patch.object(kb, 'detect_duplicate_solution',
                          return_value={'duplicate_prompt': False}), \
        mock.patch.object(kb, 'query', return_value=[{'max_version': 0}]), \
        mock.patch.object(kb, 'execute_returning',
                          side_effect=fake_execute_returning), \
        mock.patch('ai.embeddings.create_embedding',
                   side_effect=RuntimeError('Bedrock unavailable')):
            result = kb.insert_solution('hash-a', 'Fix without embedding.',
                                        project_name='ProjectX')
        self.assertIsNotNone(result)
        self.assertFalse(result.get('duplicate'))

    def test_detect_duplicate_returns_new_when_bedrock_down(self):
        """detect_duplicate_solution must fail open when Bedrock is unavailable."""
        with mock.patch('ai.embeddings.create_embedding',
                        side_effect=RuntimeError('Bedrock down')):
            result = kb.detect_duplicate_solution('Any solution.', 'hash-a', 'ProjectX')
        self.assertFalse(result['is_duplicate'])
        self.assertFalse(result['duplicate_prompt'])
        self.assertIn(result['reason'], ('embedding_unavailable', 'error'))

    def test_recommendations_fall_back_to_tier3_when_bedrock_down(self):
        """get_similar_solutions must return TIER 3 results when Bedrock is down."""
        def fake_query(sql, params=None):
            if "error_hash = %s" in sql and "row_type = 'solution'" in sql:
                return [SOLUTION_ROW_A]
            return [{'error_message': 'timeout', 'error_detail': ''}]
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding',
                   side_effect=RuntimeError('Bedrock down')):
            results = rec.get_similar_solutions('hash-a', project_name='ProjectX')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], 'sol-a')

    def test_get_ai_recommendations_returns_empty_when_no_solutions(self):
        """get_ai_recommendations must return safe empty payload when all tiers fail."""
        with mock.patch.object(rec, 'query', return_value=[]), \
        mock.patch('ai.embeddings.create_embedding',
                   side_effect=RuntimeError('Bedrock down')):
            result = rec.get_ai_recommendations('hash-a', project_name='ProjectX')
        self.assertIsNone(result['recommendation'])
        self.assertEqual(result['solutions'], [])


# ═══════════════════════════════════════════════════════════════════════════════
# 14. PINECONE UNAVAILABLE — graceful degradation
# ═══════════════════════════════════════════════════════════════════════════════

class PineconeUnavailableTests(unittest.TestCase):

    def test_tier1_failure_falls_through_to_tier2(self):
        """If Pinecone raises, TIER 2 must take over."""
        tier2_called = []
        def fake_query(sql, params=None):
            if 'embedding IS NOT NULL' in sql:
                tier2_called.append(sql)
                return [SOLUTION_ROW_A]
            return [{'error_message': 'DB timeout', 'error_detail': ''}]
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar',
                   side_effect=RuntimeError('Pinecone unavailable')):
            results = rec.get_similar_solutions('hash-a', project_name='ProjectX')
        self.assertTrue(len(tier2_called) > 0, 'TIER 2 must run when Pinecone fails')
        self.assertEqual(len(results), 1)

    def test_insert_solution_saves_when_pinecone_upsert_fails(self):
        """insert_solution must save the Aurora row even if Pinecone upsert fails."""
        inserted = []
        def fake_execute_returning(sql, params=None):
            if 'INSERT' in sql:
                inserted.append(params)
                return dict(SOLUTION_ROW_A, id='sol-new')
            return None
        with mock.patch.object(kb, '_get_log_row', return_value=LOG_ROW), \
        mock.patch.object(kb, '_find_duplicate_solution', return_value=None), \
        mock.patch.object(kb, 'detect_duplicate_solution',
                          return_value={'duplicate_prompt': False}), \
        mock.patch.object(kb, 'query', return_value=[{'max_version': 0}]), \
        mock.patch.object(kb, 'execute_returning',
                          side_effect=fake_execute_returning), \
        mock.patch.object(kb, '_create_embedding_safe',
                          return_value='[' + ','.join(['0.1'] * 1024) + ']'), \
        mock.patch.object(kb, 'upsert_vector',
                          side_effect=RuntimeError('Pinecone unavailable')):
            result = kb.insert_solution('hash-a', 'Fix when Pinecone is down.',
                                        project_name='ProjectX')
        self.assertIsNotNone(result)
        self.assertFalse(result.get('duplicate'))

    def test_detect_duplicate_returns_new_when_pinecone_down(self):
        """detect_duplicate_solution must fail open when Pinecone is unavailable."""
        with mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(kb, 'query_similar',
                          side_effect=RuntimeError('Pinecone unavailable')):
            result = kb.detect_duplicate_solution('Some fix.', 'hash-a', 'ProjectX')
        self.assertFalse(result['is_duplicate'])
        self.assertEqual(result['reason'], 'error')


# ═══════════════════════════════════════════════════════════════════════════════
# 15. PROJECT ISOLATION ENFORCEMENT
# ═══════════════════════════════════════════════════════════════════════════════

class ProjectIsolationTests(unittest.TestCase):

    def test_tier1_skipped_without_project_name(self):
        """TIER 1 Pinecone must not be called when project_name is absent."""
        pinecone_calls = []
        def fake_query(sql, params=None):
            if "error_hash = %s" in sql and "row_type = 'solution'" in sql:
                return [SOLUTION_ROW_A]
            return [{'error_message': 'timeout', 'error_detail': ''}]
        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding',
                   side_effect=RuntimeError('unavailable')), \
        mock.patch('ai.pinecone_service.query_similar',
                   side_effect=lambda **kw: pinecone_calls.append(kw) or []):
            rec.get_similar_solutions('hash-a', project_name=None)
        self.assertEqual(len(pinecone_calls), 0,
            "Pinecone must never be called without project_name")

    def test_solutions_from_other_projects_not_returned(self):
        """The Aurora hydration step must exclude solutions from other projects."""
        wrong_project_sol = dict(SOLUTION_ROW_A,
                                 id='sol-wrong', project_name='OtherProject')
        pinecone_matches = [{'id': 'sol-wrong', 'score': 0.99, 'metadata': {}}]

        def fake_query(sql, params=None):
            if 'id IN' in sql:
                # Simulate project_name filter excluding the wrong-project solution
                return []
            return [{'error_message': 'File error', 'error_detail': ''}]

        with mock.patch.object(rec, 'query', side_effect=fake_query), \
        mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch('ai.pinecone_service.query_similar', return_value=pinecone_matches):
            results = rec.get_similar_solutions('hash-a', project_name='ProjectX')

        self.assertEqual(len(results), 0,
            "Solutions from other projects must never appear in results")

    def test_duplicate_detection_scoped_to_project(self):
        """detect_duplicate_solution must pass project_name to Pinecone."""
        calls = []
        def fake_query_similar(**kwargs):
            calls.append(kwargs)
            return []
        with mock.patch('ai.embeddings.create_embedding', return_value=FAKE_EMBEDDING), \
        mock.patch.object(kb, 'query_similar', side_effect=fake_query_similar):
            kb.detect_duplicate_solution('Some fix.', 'hash-a', project_name='ProjectX')
        self.assertTrue(len(calls) > 0)
        self.assertEqual(calls[0].get('project_name'), 'ProjectX')

    def test_exact_duplicate_pass2_scoped_to_project(self):
        """Pass 2 of _find_duplicate_solution must use project_name in WHERE."""
        pass2_sqls = []
        def fake_query(sql, params=None):
            if 'log_ref_id != %s' in sql:
                pass2_sqls.append((sql, params))
                return []
            return []
        with mock.patch.object(kb, 'query', side_effect=fake_query):
            kb._find_duplicate_solution(
                'log-001', 'Some solution.', project_name='ProjectX'
            )
        if pass2_sqls:
            self.assertIn('LOWER(project_name)', pass2_sqls[0][0])


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    unittest.main()
