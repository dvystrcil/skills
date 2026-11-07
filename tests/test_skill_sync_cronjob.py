"""skill-sync reaches owui-postgres through the CNPG Pooler (argocd-projects#310).

PGO's owui-postgres-pguser-owui Secret had a `pgbouncer-uri` key. CNPG's
owui-postgres-app has none, only `fqdn-uri` for the primary
(owui-postgres-rw...). The CronJob's shell swaps that host for the Pooler's
Service, the same swap as dvystrcil/open-webui's base/pooler-database-url.py,
and refuses to run if the host is not there exactly once.

These run the SHIPPED command from sync_to_owui.yaml (its DATABASE_URL lines),
not a re-implementation of it.
"""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RW = "owui-postgres-rw.open-webui.svc.cluster.local"
POOLER = "owui-postgres-pooler-rw.open-webui.svc.cluster.local"
PW = "a%40b%2Fc%3Bd%3Ae"  # URL-encoded, as CNPG writes it


def cronjob():
    return yaml.safe_load((ROOT / "sync_to_owui.yaml").read_text())


def container():
    return cronjob()["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]


def prelude():
    """The command up to and including `export DATABASE_URL`."""
    script = container()["command"][2]
    head, sep, _ = script.partition("export DATABASE_URL")
    assert sep, "command no longer exports DATABASE_URL"
    return head + sep


def run_prelude(value):
    env = {k: v for k, v in os.environ.items() if k not in ("DB_URL_RW", "DATABASE_URL")}
    if value is not None:
        env["DB_URL_RW"] = value
    py = shutil.which("python3")
    # The image has `python`; on the runner it may only be python3.
    shim = f'python() {{ "{py}" "$@"; }}\n'
    return subprocess.run(["sh", "-c", shim + prelude() + '\nprintf %s "$DATABASE_URL"'],
                          env=env, capture_output=True, text=True)


class TestSkillSyncCronJob(unittest.TestCase):
    def test_not_suspended(self):
        self.assertNotIn("suspend", cronjob()["spec"])

    def test_source_is_the_cnpg_app_secret_fqdn_uri(self):
        env = {e["name"]: e for e in container()["env"]}
        self.assertNotIn("DATABASE_URL", env)
        ref = env["DB_URL_RW"]["valueFrom"]["secretKeyRef"]
        self.assertEqual((ref["name"], ref["key"]), ("owui-postgres-app", "fqdn-uri"))

    def test_swaps_the_primary_host_for_the_pooler(self):
        r = run_prelude(f"postgresql://owui:{PW}@{RW}:5432/owui")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"postgresql://owui:{PW}@{POOLER}:5432/owui")

    def test_missing_env_stops_the_job(self):
        r = run_prelude(None)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_unexpected_host_stops_the_job_without_printing_the_password(self):
        r = run_prelude(f"postgresql://owui:{PW}@elsewhere:5432/owui")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertNotIn(PW, r.stderr)

    def test_host_twice_stops_the_job(self):
        r = run_prelude(f"postgresql://owui:{PW}@{RW}:5432/owui?x=@{RW}:")
        self.assertNotEqual(r.returncode, 0)

    def test_sync_still_runs_after_the_prelude(self):
        script = container()["command"][2]
        self.assertGreater(script.index("python /skills/sync_to_owui.py"),
                           script.index("export DATABASE_URL"))


if __name__ == "__main__":
    unittest.main()
