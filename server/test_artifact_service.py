import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from server.artifact_service import preview_content, render_static_html, resolve_artifact_path


class ArtifactServiceTests(unittest.TestCase):
    def test_static_html_escapes_model_content_and_has_restrictive_policy(self):
        rendered = render_static_html(
            '标题 <script>alert("title")</script>',
            '# 小节\n\n<script>alert("body")</script>\n\n'
            '<form action="https://evil.example"><input autofocus onfocus="alert(1)"></form>',
        )
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn('<script>alert("body")</script>', rendered)
        self.assertNotIn("<form action=", rendered)
        self.assertNotIn("<input autofocus", rendered)
        self.assertIn("default-src 'none'", rendered)
        self.assertIn("form-action 'none'", rendered)
        self.assertIn("base-uri 'none'", rendered)

    def test_preview_rejects_modified_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "user" / "artifact.html"
            path.parent.mkdir()
            original = b"<!doctype html><p>trusted</p>"
            path.write_bytes(original)
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.execute("""CREATE TABLE artifacts (
                kind TEXT, filename TEXT, storage_path TEXT, content_sha256 TEXT
            )""")
            conn.execute(
                "INSERT INTO artifacts VALUES ('html', 'artifact.html', ?, ?)",
                (str(path), hashlib.sha256(original).hexdigest()),
            )
            row = conn.execute("SELECT * FROM artifacts").fetchone()
            path.write_text("<script>alert(1)</script>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "完整性校验失败"):
                preview_content(row, root)
            conn.close()

    def test_path_outside_artifact_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "artifacts"
            outside = base / "outside.html"
            root.mkdir()
            outside.write_text("outside", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                resolve_artifact_path(str(outside), root)


if __name__ == "__main__":
    unittest.main()
