import tempfile
import unittest
from pathlib import Path

from app.indexer import RepoIndexer, compute_file_hash, parse_python_ast
from app.llm import classify_with_python, route_task
from app.patcher import apply_patch, create_unified_diff, validate_patch


class TestJarvisCore(unittest.TestCase):
    def test_task_router(self):
        self.assertEqual(route_task("create file auth/login.py").task_type, "CREATE")
        self.assertEqual(route_task("update function login()").task_type, "UPDATE")
        self.assertEqual(route_task("find function validate_user in the repository").task_type, "SEARCH")
        self.assertEqual(route_task("fix bug with traceback").task_type, "DEBUG")
        self.assertEqual(route_task("run tests with pytest").task_type, "TEST")

    def test_indexer_ast_parsing(self):
        sample = (
            "def login(user, pwd):\n"
            "    return True\n\n"
            "class AuthManager:\n"
            "    def validate(self):\n"
            "        return True\n"
        )
        parsed = parse_python_ast(sample)
        self.assertEqual(len(parsed["functions"]), 1)
        self.assertEqual(parsed["functions"][0]["name"], "login")
        self.assertEqual(len(parsed["classes"]), 1)
        self.assertEqual(parsed["classes"][0]["name"], "AuthManager")
        self.assertEqual(len(parsed["classes"][0]["methods"]), 1)
        self.assertEqual(parsed["classes"][0]["methods"][0]["name"], "validate")

    def test_incremental_indexing(self):
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            indexer = RepoIndexer(workspace=ws)

            # File 1
            f1 = ws / "module1.py"
            f1.write_text("def fn1(): pass\n", encoding="utf-8")
            res_add = indexer.sync()
            self.assertIn("module1.py", res_add["added"])
            self.assertEqual(len(indexer.get_map()), 1)

            # Sync no changes
            res_same = indexer.sync()
            self.assertEqual(res_same["added"], [])
            self.assertEqual(res_same["modified"], [])

            # Modify File 1
            f1.write_text("def fn1(): pass\ndef fn2(): pass\n", encoding="utf-8")
            res_mod = indexer.sync()
            self.assertIn("module1.py", res_mod["modified"])
            self.assertEqual(len(indexer.get_map()["module1.py"]["functions"]), 2)

            # Delete File 1
            f1.unlink()
            res_del = indexer.sync()
            self.assertIn("module1.py", res_del["deleted"])
            self.assertNotIn("module1.py", indexer.get_map())

    def test_localization_and_context(self):
        code = (
            "import os\n"
            "from sys import version\n\n"
            "def authenticate(username, password):\n"
            "    if not username:\n"
            "        return False\n"
            "    return True\n"
        )
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            indexer = RepoIndexer(workspace=ws)
            auth_file = ws / "auth.py"
            auth_file.write_text(code, encoding="utf-8")
            indexer.scan_all()

            # Locate
            matches = indexer.locate("Add validation to authenticate function")
            self.assertTrue(len(matches) >= 1)
            self.assertEqual(matches[0]["symbol"], "authenticate")
            self.assertEqual(matches[0]["file"], "auth.py")

            # Context retrieval
            ctx = indexer.get_context("auth.py", symbol_name="authenticate", padding=1)
            self.assertIsNotNone(ctx)
            self.assertIn("def authenticate", ctx["code"])
            self.assertIn("import os", ctx["imports"])

    def test_semantic_locate_validation(self):
        """Test that semantic fallback validates class methods and rejects hallucinated symbols."""
        code = (
            "class AuthManager:\n"
            "    def authenticate(self, user, pwd):\n"
            "        return True\n"
        )
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            indexer = RepoIndexer(workspace=ws)
            (ws / "auth.py").write_text(code, encoding="utf-8")
            indexer.scan_all()

            # Mock semantic fallback with:
            # 1. Valid method 'AuthManager.authenticate'
            # 2. Hallucinated file 'ghost.py'
            # 3. Hallucinated symbol 'auth.py: non_existent_fn' (must be discarded!)
            mock_llm_json = (
                '[{"file": "auth.py", "symbol": "AuthManager.authenticate", "reason": "Handles credentials"},'
                ' {"file": "ghost.py", "symbol": "fake", "reason": "Hallucinated file"},'
                ' {"file": "auth.py", "symbol": "non_existent_fn", "reason": "Hallucinated symbol"}]'
            )
            import unittest.mock as mock

            with mock.patch("httpx.post") as mock_post:
                mock_resp = mock.MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "choices": [{"message": {"content": mock_llm_json}}]
                }
                mock_post.return_value = mock_resp

                matches = indexer._semantic_locate("I need to manage user credentials and verification")
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["file"], "auth.py")
                self.assertEqual(matches[0]["symbol"], "AuthManager.authenticate")
                self.assertEqual(matches[0]["type"], "method")
                self.assertTrue(matches[0]["semantic"])

    def test_patch_validation_and_application(self):
        code = "def greet():\n    print('hello')\n"
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            f = ws / "app.py"
            f.write_text(code, encoding="utf-8")
            h = compute_file_hash(code)

            # 1. Non-matching snippet
            valid, msg = validate_patch("app.py", "invalid_text", "new_text", workspace=ws)
            self.assertFalse(valid)

            # 2. Stale expected hash
            valid, msg = validate_patch("app.py", "print('hello')", "print('hi')", expected_hash="dummy", workspace=ws)
            self.assertFalse(valid)

            # 3. Valid patch
            valid, msg = validate_patch("app.py", "print('hello')", "print('hi')", expected_hash=h, workspace=ws)
            self.assertTrue(valid)

            # 4. Apply patch
            res = apply_patch(
                "app.py",
                "print('hello')",
                "print('hi')",
                reason="simplify greeting",
                expected_hash=h,
                require_approval=False,
                workspace=ws,
            )
            self.assertTrue(res.success)
            self.assertIn("-    print('hello')", res.diff)
            self.assertIn("+    print('hi')", res.diff)
            self.assertEqual(f.read_text(encoding="utf-8"), "def greet():\n    print('hi')\n")


if __name__ == "__main__":
    unittest.main()

