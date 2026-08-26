import importlib.util
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "skills" / "quant-buddy-skill" / "scripts" / "self_update.py"
spec = importlib.util.spec_from_file_location("qbs_self_update_test", MODULE_PATH)
SU = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SU)


def write_skill(root: Path, version: str, marker: str):
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(f"---\nversion: {version}\n---\n{marker}\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(marker, encoding="utf-8")
    (root / "scripts" / "call.py").write_text(marker, encoding="utf-8")
    (root / "scripts" / "executor.py").write_text(marker, encoding="utf-8")
    (root / "tools" / "tool.md").write_text(marker, encoding="utf-8")
    (root / "workflows" / "workflow.md").write_text(marker, encoding="utf-8")


class QbsSelfUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workbuddy = Path(self.tmp.name) / "workbuddy"
        self.skill_root = self.workbuddy / "skills" / "quant-buddy-skill__skillhub"
        write_skill(self.skill_root, "4.25.28", "old")
        (self.skill_root / "config.json").write_text('{"saved": true}', encoding="utf-8")
        (self.skill_root / "output").mkdir()
        (self.skill_root / "output" / "state.txt").write_text("keep", encoding="utf-8")
        (self.skill_root / "logs").mkdir()
        (self.skill_root / "logs" / "keep.log").write_text("keep", encoding="utf-8")
        self.source = Path(self.tmp.name) / "source"
        write_skill(self.source, "4.25.29", "new")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_backup_location_is_managed_workbuddy_path(self):
        self.assertEqual(
            SU._default_backup_root(self.skill_root),
            self.workbuddy / "backups" / "skills" / "quant-buddy-skill",
        )

    def test_install_creates_metadata_and_preserves_runtime_state(self):
        backup_root = SU._default_backup_root(self.skill_root)
        backup = SU._install(self.source, self.skill_root, backup_root, "4.25.29")
        self.assertTrue(backup.is_dir())
        metadata = json.loads((backup / SU.BACKUP_METADATA_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(metadata["skill_slug"], SU.SKILL_SLUG)
        self.assertEqual(metadata["replaced_version"], "4.25.28")
        self.assertEqual(SU._read_skill_version(self.skill_root / "SKILL.md"), "4.25.29")
        self.assertEqual((self.skill_root / "config.json").read_text(encoding="utf-8"), '{"saved": true}')
        self.assertEqual((self.skill_root / "output" / "state.txt").read_text(encoding="utf-8"), "keep")
        self.assertEqual((self.skill_root / "logs" / "keep.log").read_text(encoding="utf-8"), "keep")

    def test_install_rolls_back_when_swap_fails(self):
        backup_root = SU._default_backup_root(self.skill_root)
        original_swap = SU._atomic_swap_item
        calls = []
        def fail_after_first(staged, target, trash):
            if calls:
                raise RuntimeError("forced swap failure")
            calls.append(target.name)
            return original_swap(staged, target, trash)
        SU._atomic_swap_item = fail_after_first
        try:
            with self.assertRaisesRegex(RuntimeError, "forced swap failure"):
                SU._install(self.source, self.skill_root, backup_root, "4.25.29")
        finally:
            SU._atomic_swap_item = original_swap
        self.assertEqual(SU._read_skill_version(self.skill_root / "SKILL.md"), "4.25.28")
        self.assertEqual((self.skill_root / "scripts" / "call.py").read_text(encoding="utf-8"), "old")

    def test_migrate_only_recognized_legacy_backup_then_prune_metadata_backups(self):
        managed = SU._default_backup_root(self.skill_root)
        legacy = self.workbuddy / "quant-buddy-skill-backup-20260824161930"
        write_skill(legacy, "4.25.10", "legacy")
        (legacy / "_skillhub_meta.json").write_text(json.dumps({"slug": SU.SKILL_SLUG}), encoding="utf-8")
        unknown = self.workbuddy / "quant-buddy-skill-backup-manual"
        unknown.mkdir()
        migrated = SU._migrate_legacy_backups(self.skill_root, managed)
        self.assertEqual(len(migrated), 1)
        self.assertFalse(legacy.exists())
        self.assertTrue(unknown.exists())
        moved = Path(migrated[0]["to"])
        self.assertEqual(json.loads((moved / SU.BACKUP_METADATA_FILENAME).read_text(encoding="utf-8"))["skill_slug"], SU.SKILL_SLUG)

        now = time.time()
        for index, age_days in enumerate((1, 2, 3, 4, 31)):
            candidate = managed / f"quant-buddy-skill-backup-202608{index:02d}-v4.25.{index}"
            candidate.mkdir(parents=True, exist_ok=True)
            (candidate / SU.BACKUP_METADATA_FILENAME).write_text(json.dumps({
                "schema": SU.BACKUP_METADATA_SCHEMA,
                "skill_slug": SU.SKILL_SLUG,
                "created_at_epoch": now - age_days * 86400,
            }), encoding="utf-8")
        protected = managed / ".staging"
        protected.mkdir(exist_ok=True)
        (managed / "manual-not-a-backup").mkdir(exist_ok=True)
        pruned = SU._prune_managed_backups(managed, now=now)
        self.assertGreaterEqual(len(pruned), 3)
        valid = [p for p in managed.iterdir() if p.is_dir() and (p / SU.BACKUP_METADATA_FILENAME).exists()]
        self.assertLessEqual(len(valid), SU.BACKUP_RETENTION_COUNT)
        self.assertTrue(protected.exists())
        self.assertTrue((managed / "manual-not-a-backup").exists())


if __name__ == "__main__":
    unittest.main()
