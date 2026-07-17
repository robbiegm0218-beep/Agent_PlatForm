import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
SERVICES = ("auth_service.py", "knowledge_service.py", "space_service.py", "chat_service.py")


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_domain_services_do_not_import_app(self):
        for name in SERVICES:
            tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
            imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            self.assertNotIn("server.app", imports, name)

    def test_server_has_a_canonical_module_entrypoint(self):
        entrypoint = (ROOT / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("from server.app import main", entrypoint)

    def test_app_uses_package_imports_for_core_modules(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertNotIn("except ModuleNotFoundError:", source)
        self.assertIn("from server.http_routes import API_ROUTES", source)


if __name__ == "__main__":
    unittest.main()
