#!/usr/bin/env python3
"""Sync skills/owui/*/SKILL.md to the OWI Postgres database.

Reads every SKILL.md under skills/owui/, strips YAML frontmatter, and upserts
each skill into the `skill` table. Skips rows whose content hash hasn't changed.
"""

import hashlib
import os
import re
import sys
import time
from pathlib import Path

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set", file=sys.stderr)
    sys.exit(1)

# When running from a ConfigMap mount, SKILLS_FLAT_DIR points to a flat
# directory of *.md files (one per skill). Otherwise fall back to the
# structured owui/ tree next to this script.
_flat_dir = os.environ.get("SKILLS_FLAT_DIR")
if _flat_dir:
    SKILLS_FLAT_DIR = Path(_flat_dir)
    SKILLS_DIR = None
else:
    SKILLS_FLAT_DIR = None
    SKILLS_DIR = Path(__file__).parent / "owui"

# Admin user ID — owner assigned to created skills
# Falls back to querying for the first admin user
ADMIN_USER_ID = os.environ.get("OWUI_ADMIN_USER_ID")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_skill_file(path: Path, skill_id: str | None = None) -> dict | None:
    text = path.read_text()
    m = FRONTMATTER_RE.match(text)
    if not m:
        print(f"  SKIP {path}: no frontmatter", file=sys.stderr)
        return None

    body = text[m.end():].strip()
    fm_text = m.group(1)

    # Simple key: "value" parser (no full YAML dependency needed)
    meta = {}
    for line in fm_text.splitlines():
        kv = line.split(":", 1)
        if len(kv) == 2:
            key = kv[0].strip()
            val = kv[1].strip().strip('"').strip("'")
            # Strip inline arrays for tags
            if val.startswith("["):
                val = re.sub(r'[\[\]"]', "", val)
                val = ", ".join(v.strip() for v in val.split(","))
            meta[key] = val

    if skill_id is None:
        skill_id = path.parent.name  # directory name = skill slug
    return {
        "id": skill_id,
        "name": meta.get("name", skill_id),
        "description": meta.get("description", ""),
        "content": body,
        "meta": {"tags": meta.get("tags", ""), "scope": meta.get("scope", "")},
    }


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def main():
    if SKILLS_FLAT_DIR:
        skill_files = sorted(SKILLS_FLAT_DIR.glob("*.md"))
        flat_mode = True
    else:
        skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))
        flat_mode = False
    if not skill_files:
        src = SKILLS_FLAT_DIR or SKILLS_DIR
        print(f"No skill files found under {src}")
        sys.exit(0)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Resolve admin user ID if not provided
    admin_user_id = ADMIN_USER_ID
    if not admin_user_id:
        cur.execute("SELECT id FROM \"user\" WHERE role='admin' LIMIT 1")
        row = cur.fetchone()
        if not row:
            print("ERROR: no admin user found in DB", file=sys.stderr)
            sys.exit(1)
        admin_user_id = row[0]

    created = updated = skipped = errors = 0
    now = int(time.time())

    import json

    for path in skill_files:
        sid_override = path.stem if flat_mode else None
        skill = parse_skill_file(path, skill_id=sid_override)
        if skill is None:
            errors += 1
            continue

        sid = skill["id"]
        new_hash = content_hash(skill["content"] + skill["name"] + skill["description"])

        # Match by name (unique constraint) — existing skills may have different IDs
        # (created via UI). Use name as the stable lookup key.
        cur.execute("SELECT id, content, description FROM skill WHERE name = %s", (skill["name"],))
        existing = cur.fetchone()

        if existing:
            existing_id, existing_content, existing_desc = existing
            old_hash = content_hash(existing_content + skill["name"] + (existing_desc or ""))
            if old_hash == new_hash:
                print(f"  SKIP    {existing_id!r} (name={skill['name']!r}, unchanged)")
                skipped += 1
                continue
            cur.execute(
                "UPDATE skill SET description=%s, content=%s, meta=%s, updated_at=%s WHERE id=%s",
                (skill["description"], skill["content"], json.dumps(skill["meta"]), now, existing_id),
            )
            print(f"  UPDATE  {existing_id!r} (name={skill['name']!r})")
            updated += 1
        else:
            cur.execute(
                """INSERT INTO skill (id, user_id, name, description, content, meta, is_active, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s)""",
                (sid, admin_user_id, skill["name"], skill["description"],
                 skill["content"], json.dumps(skill["meta"]), now, now),
            )
            print(f"  CREATE  {sid!r} (name={skill['name']!r})")
            created += 1

    conn.commit()
    conn.close()

    print(f"\nDone: created={created} updated={updated} skipped={skipped} errors={errors}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
