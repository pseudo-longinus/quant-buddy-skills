import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VIEW_SCRIPTS = REPO / "skills" / "quant-buddy-view" / "scripts"
if str(VIEW_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(VIEW_SCRIPTS))

import common as C
import formula_package as FP
import qbs_bridge as Bridge
import static_page as SP


class QbsSkillResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.skills = self.root / "skills"
        self.qbv = self.skills / "quant-buddy-view__skillhub"
        (self.qbv / "scripts").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _qbs(self, name):
        path = self.skills / name
        (path / "scripts").mkdir(parents=True)
        (path / "scripts" / "call.py").write_text("# executable marker\n", encoding="utf-8")
        return path

    def test_prefers_traditional_exact_directory(self):
        traditional = self._qbs("quant-buddy-skill")
        self._qbs("quant-buddy-skill__skillhub")
        result = C.resolve_qbs_skill_root(qbv_skill_root=self.qbv, environ={})
        self.assertEqual(result["root"], traditional)
        self.assertFalse(result["used_env_override"])

    def test_falls_back_to_skillhub_and_never_selects_backup(self):
        backup = self._qbs("quant-buddy-skill-backup-20260824161930")
        skillhub = self._qbs("quant-buddy-skill__skillhub")
        result = C.resolve_qbs_skill_root(qbv_skill_root=self.qbv, environ={})
        self.assertEqual(result["root"], skillhub)
        self.assertNotEqual(result["root"], backup)
        self.assertEqual(result["searched_roots"], [
            str((self.skills / "quant-buddy-skill").resolve()),
            str(skillhub.resolve()),
        ])

    def test_environment_override_has_highest_priority(self):
        traditional = self._qbs("quant-buddy-skill")
        override = self.root / "override-qbs"
        (override / "scripts").mkdir(parents=True)
        (override / "scripts" / "call.py").write_text("# executable marker\n", encoding="utf-8")
        result = C.resolve_qbs_skill_root(qbv_skill_root=self.qbv, environ={"QBS_SKILL_ROOT": str(override)})
        self.assertEqual(result["root"], override.resolve())
        self.assertTrue(result["used_env_override"])
        self.assertNotIn(str(traditional.resolve()), result["searched_roots"])

    def test_consumers_share_resolver_and_missing_diagnostics(self):
        skillhub = self._qbs("quant-buddy-skill__skillhub")
        (skillhub / "presets" / "assets_db").mkdir(parents=True)
        (skillhub / "output" / "formula_packages").mkdir(parents=True)
        original_root = C.SKILL_ROOT
        old_env = os.environ.pop("QBS_SKILL_ROOT", None)
        try:
            C.SKILL_ROOT = str(self.qbv)
            Bridge.QBV_ROOT = self.qbv
            self.assertEqual(Bridge._qbs_root(), skillhub.resolve())
            self.assertEqual(Path(SP._assets_db_dir()), skillhub / "presets" / "assets_db")
            source, source_kind = FP._resolve_import_dir({})
            self.assertEqual(Path(source), skillhub / "output" / "formula_packages")
            self.assertEqual(source_kind, "default(resolved qbs skill)")

            (skillhub / "scripts" / "call.py").unlink()
            resolution = C.resolve_qbs_skill_root(qbv_skill_root=self.qbv, environ={})
            payload = Bridge._qbs_not_found_payload(resolution)
            self.assertEqual(payload["error"], "QBS_NOT_FOUND")
            self.assertEqual(payload["searched_roots"], [
                str((self.skills / "quant-buddy-skill").resolve()),
                str(skillhub.resolve()),
            ])
            self.assertEqual(payload["call_script"], str(skillhub / "scripts" / "call.py"))
            self.assertFalse(payload["used_env_override"])
        finally:
            C.SKILL_ROOT = original_root
            if old_env is not None:
                os.environ["QBS_SKILL_ROOT"] = old_env

    def test_validation_receipts_are_task_scoped_temp_files(self):
        old_temp = tempfile.tempdir
        with tempfile.TemporaryDirectory() as temp_root:
            tempfile.tempdir = temp_root
            try:
                task_id = "task/with spaces"
                receipt = Bridge._write_live_data_route_receipt({"task_id": task_id, "status": "live"})
                self.assertEqual(Path(receipt).parent, C.task_temp_dir(task_id) / "live_data_route_receipts")
                grant = Bridge._grant_validation_receipt(task_id, "snapshot", "fast_query", "abc")
                self.assertEqual(Path(grant).parent, C.task_temp_dir(task_id) / "grant_validation_receipts")
            finally:
                tempfile.tempdir = old_temp


if __name__ == "__main__":
    unittest.main()
