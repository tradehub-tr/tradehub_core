#!/usr/bin/env python3
"""Create and inspect the disposable T-044 scale benchmark database.

The script never touches a Frappe site database.  It only accepts database
names beginning with ``media_phase4_bench_`` and a drop additionally requires
the exact name through ``--confirm-drop``.  Credentials stay inside the
MariaDB container: the client reads ``MYSQL_ROOT_PASSWORD`` there, so the
secret is never placed in the host process list or output.

Examples::

    python scripts/seed_synthetic.py prepare
    python scripts/seed_synthetic.py seed-assets
    python scripts/seed_synthetic.py seed-renditions
    python scripts/seed_synthetic.py indexes
    python scripts/seed_synthetic.py explain
    python scripts/seed_synthetic.py drop --confirm-drop media_phase4_bench_20260823
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

DEFAULT_DATABASE = "media_phase4_bench_20260823"
DEFAULT_CONTAINER = "istoc-dev-db-1"
DATABASE_RE = re.compile(r"^media_phase4_bench_[a-z0-9_]+$")


@dataclass
class Runner:
	container: str
	database: str

	def sql(self, statement: str, *, database: bool = False) -> str:
		command = [
			"docker",
			"exec",
			"-i",
			self.container,
			"sh",
			"-lc",
			'exec mariadb --batch --raw --skip-column-names -uroot '
			'-p"${MARIADB_ROOT_PASSWORD:-$MYSQL_ROOT_PASSWORD}"',
		]
		payload = f"USE `{self.database}`;\n{statement}" if database else statement
		completed = subprocess.run(
			command,
			input=payload,
			text=True,
			capture_output=True,
			check=False,
		)
		if completed.returncode:
			raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
		return completed.stdout.strip()

	def exists(self) -> bool:
		out = self.sql(
			"SELECT COUNT(*) FROM information_schema.schemata "
			f"WHERE schema_name = '{self.database}';"
		)
		return out.strip() == "1"


def _phase(label: str, fn) -> dict[str, Any]:
	print(f"[faz4-bench] {label} başladı", file=sys.stderr, flush=True)
	started = time.monotonic()
	value = fn()
	elapsed = round(time.monotonic() - started, 3)
	print(f"[faz4-bench] {label} tamamlandı: {elapsed}s", file=sys.stderr, flush=True)
	return {"seconds": elapsed, "result": value}


def prepare(runner: Runner) -> dict[str, Any]:
	if runner.exists():
		raise RuntimeError(
			f"{runner.database} zaten var; önce açıkça drop --confirm-drop {runner.database} çalıştırın"
		)
	runner.sql(
		f"CREATE DATABASE `{runner.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
	)
	runner.sql(
		"""
CREATE TABLE digit (n TINYINT UNSIGNED NOT NULL PRIMARY KEY) ENGINE=InnoDB;
INSERT INTO digit VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9);

CREATE TABLE media_asset (
  name VARCHAR(20) NOT NULL PRIMARY KEY,
  owner_seller VARCHAR(24) NOT NULL,
  slot_key VARCHAR(32) NOT NULL,
  state VARCHAR(16) NOT NULL,
  modified DATETIME(6) NOT NULL,
  creation DATETIME(6) NOT NULL,
  last_access_at DATETIME NULL,
  legal_hold TINYINT(1) NOT NULL DEFAULT 0,
  content_sha256 CHAR(64) NOT NULL,
  asset_key VARCHAR(140) NOT NULL
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;

CREATE TABLE media_version (
  name CHAR(64) NOT NULL PRIMARY KEY,
  asset VARCHAR(20) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;

CREATE TABLE media_rendition (
  name VARCHAR(32) NOT NULL PRIMARY KEY,
  asset VARCHAR(20) NOT NULL,
  version_hash CHAR(64) NOT NULL,
  profile VARCHAR(16) NOT NULL,
  width INT NOT NULL,
  format VARCHAR(8) NOT NULL,
  bytes INT NOT NULL,
  last_access_at DATETIME NULL
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;

CREATE TABLE media_usage (
  name VARCHAR(32) NOT NULL PRIMARY KEY,
  asset VARCHAR(20) NOT NULL,
  ref_doctype VARCHAR(32) NOT NULL,
  ref_name VARCHAR(32) NOT NULL,
  ref_field VARCHAR(32) NOT NULL,
  is_open TINYINT(1) NOT NULL,
  last_seen DATETIME NOT NULL
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;

CREATE TABLE media_processing_job (
  name VARCHAR(32) NOT NULL PRIMARY KEY,
  asset VARCHAR(20) NOT NULL,
  queue VARCHAR(32) NOT NULL,
  status VARCHAR(16) NOT NULL,
  modified DATETIME(6) NOT NULL
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC;
""",
		database=True,
	)
	return {"database": runner.database, "tables": 6}


def seed_assets(runner: Runner) -> dict[str, int]:
	runner.sql(
		"""
SET autocommit=0;
INSERT INTO media_asset
  (name, owner_seller, slot_key, state, modified, creation, last_access_at,
   legal_hold, content_sha256, asset_key)
SELECT
  CONCAT('MA-', LPAD(seq.n, 9, '0')),
  CONCAT('SELLER-', LPAD(MOD(seq.n, 1000), 4, '0')),
  CASE MOD(seq.n, 3) WHEN 0 THEN 'product.image' WHEN 1 THEN 'seller.logo' ELSE 'category.banner' END,
  CASE MOD(seq.n, 10) WHEN 0 THEN 'draft' WHEN 1 THEN 'archived' ELSE 'ready' END,
  TIMESTAMP('2026-08-23 00:00:00') - INTERVAL MOD(seq.n, 86400) SECOND,
  TIMESTAMP('2025-01-01 00:00:00') + INTERVAL MOD(seq.n, 500) DAY,
  TIMESTAMP('2026-08-23 00:00:00') - INTERVAL MOD(seq.n, 180) DAY,
  IF(MOD(seq.n, 10000)=0, 1, 0),
  LPAD(HEX(seq.n), 64, '0'),
  CONCAT('SELLER-', LPAD(MOD(seq.n, 1000), 4, '0'), '|',
         CASE MOD(seq.n, 3) WHEN 0 THEN 'product.image' WHEN 1 THEN 'seller.logo' ELSE 'category.banner' END,
         '|', LPAD(HEX(seq.n), 64, '0'))
FROM (
  SELECT a.n + 10*b.n + 100*c.n + 1000*d.n + 10000*e.n + 100000*f.n AS n
  FROM digit a CROSS JOIN digit b CROSS JOIN digit c
  CROSS JOIN digit d CROSS JOIN digit e CROSS JOIN digit f
) seq;

INSERT INTO media_version (name, asset, is_active, created_at)
SELECT content_sha256, name, 1, creation FROM media_asset;

INSERT INTO media_usage (name, asset, ref_doctype, ref_name, ref_field, is_open, last_seen)
SELECT CONCAT('MU-', SUBSTRING(name, 4)), name, 'Listing',
       CONCAT('LIST-', SUBSTRING(name, 4)), 'primary_image', 1, modified
FROM media_asset WHERE MOD(CONV(SUBSTRING(name, 4), 10, 10), 5) <> 0;

INSERT INTO media_processing_job (name, asset, queue, status, modified)
SELECT CONCAT('MJ-', SUBSTRING(name, 4)), name,
       CASE MOD(CONV(SUBSTRING(name, 4), 10, 10), 5)
         WHEN 0 THEN 'media-image-live' WHEN 1 THEN 'media-image-bulk'
         WHEN 2 THEN 'media-video' WHEN 3 THEN 'media-ai' ELSE 'media-maint' END,
       CASE MOD(CONV(SUBSTRING(name, 4), 10, 10), 4)
         WHEN 0 THEN 'queued' WHEN 1 THEN 'running' WHEN 2 THEN 'done' ELSE 'failed' END,
       modified
FROM media_asset;
COMMIT;
""",
		database=True,
	)
	return counts(runner)


def seed_renditions(runner: Runner) -> dict[str, int]:
	runner.sql(
		"""
SET autocommit=0;
INSERT INTO media_rendition
  (name, asset, version_hash, profile, width, format, bytes, last_access_at)
SELECT
  CONCAT('MR-', SUBSTRING(a.name, 4), '-', LPAD(r.n, 2, '0')),
  a.name,
  a.content_sha256,
  CONCAT('p', LPAD(FLOOR(r.n / 3), 2, '0')),
  96 * (FLOOR(r.n / 3) + 1),
  CASE MOD(r.n, 3) WHEN 0 THEN 'avif' WHEN 1 THEN 'webp' ELSE 'jpeg' END,
  2048 + MOD(CONV(SUBSTRING(a.name, 4), 10, 10) * 31 + r.n * 997, 250000),
  a.last_access_at
FROM media_asset a
CROSS JOIN (
  SELECT x.n + 10*y.n AS n FROM digit x CROSS JOIN digit y
  WHERE x.n + 10*y.n < 30
) r;
COMMIT;
""",
		database=True,
	)
	return counts(runner)


def install_indexes(runner: Runner) -> dict[str, int]:
	runner.sql(
		"""
ALTER TABLE media_asset
  ADD UNIQUE KEY uk_asset_key (asset_key),
  ADD KEY ix_content_sha256 (content_sha256),
  ADD KEY ix_seller_state_modified (owner_seller, state, modified),
  ADD KEY ix_state_lastaccess (state, last_access_at),
  ADD KEY ix_state_hold_creation (state, legal_hold, creation);
ALTER TABLE media_version
  ADD KEY ix_asset_active (asset, is_active);
ALTER TABLE media_rendition
  ADD UNIQUE KEY uk_rendition_quad (version_hash, profile, width, format),
  ADD KEY ix_rendition_asset_version (asset, version_hash, profile),
  ADD KEY ix_rendition_last_access (last_access_at);
ALTER TABLE media_usage
  ADD UNIQUE KEY uk_usage_quad (asset, ref_doctype, ref_name, ref_field),
  ADD KEY ix_asset_open (asset, is_open),
  ADD KEY ix_ref (ref_doctype, ref_name);
ALTER TABLE media_processing_job
  ADD KEY ix_queue_status_modified (queue, status, modified),
  ADD KEY ix_job_asset_status (asset, status);
ANALYZE TABLE media_asset, media_version, media_rendition, media_usage, media_processing_job;
""",
		database=True,
	)
	return counts(runner)


def counts(runner: Runner) -> dict[str, int]:
	out = runner.sql(
		"""
SELECT 'media_asset', COUNT(*) FROM media_asset
UNION ALL SELECT 'media_version', COUNT(*) FROM media_version
UNION ALL SELECT 'media_rendition', COUNT(*) FROM media_rendition
UNION ALL SELECT 'media_usage', COUNT(*) FROM media_usage
UNION ALL SELECT 'media_processing_job', COUNT(*) FROM media_processing_job;
""",
		database=True,
	)
	return {line.split("\t", 1)[0]: int(line.split("\t", 1)[1]) for line in out.splitlines()}


def storage_stats(runner: Runner) -> dict[str, Any]:
	version = runner.sql("SELECT VERSION();").strip()
	out = runner.sql(
		"""
SELECT table_name, table_rows, data_length, index_length
FROM information_schema.tables
WHERE table_schema = DATABASE()
  AND table_name IN ('media_asset','media_version','media_rendition','media_usage','media_processing_job')
ORDER BY table_name;
""",
		database=True,
	)
	tables: dict[str, dict[str, int]] = {}
	for line in out.splitlines():
		name, estimated_rows, data_bytes, index_bytes = line.split("\t")
		tables[name] = {
			"estimated_rows": int(estimated_rows),
			"data_bytes": int(data_bytes),
			"index_bytes": int(index_bytes),
		}
	return {"mariadb": version, "tables": tables}


QUERIES: dict[str, str] = {
	"seller_library": """SELECT name, modified FROM media_asset
WHERE owner_seller='SELLER-0042' AND state='ready'
ORDER BY modified DESC LIMIT 50""",
	"asset_renditions": """SELECT profile, width, format, bytes FROM media_rendition
WHERE asset='MA-000000042' AND version_hash=LPAD(HEX(42),64,'0')
ORDER BY profile, width, format""",
	"dedup_lookup": """SELECT name FROM media_asset
WHERE content_sha256=LPAD(HEX(420042),64,'0') LIMIT 1""",
	"orphan_report": """SELECT a.name FROM media_asset a
WHERE a.state='ready' AND a.legal_hold=0
  AND a.creation < '2026-07-24'
  AND NOT EXISTS (SELECT 1 FROM media_usage u WHERE u.asset=a.name AND u.is_open=1)
ORDER BY a.creation LIMIT 100""",
	"retention_scan": """SELECT name FROM media_asset
WHERE state='ready' AND last_access_at < '2026-05-25'
ORDER BY last_access_at LIMIT 100""",
	"queue_status": """SELECT status, COUNT(*) FROM media_processing_job
WHERE queue='media-image-live' GROUP BY status""",
	"rendition_identity": """SELECT name FROM media_rendition
WHERE version_hash=LPAD(HEX(42),64,'0') AND profile='p00'
  AND width=96 AND format='avif'""",
}


def explain(runner: Runner) -> dict[str, Any]:
	result: dict[str, Any] = {
		"counts": counts(runner),
		"storage": storage_stats(runner),
		"queries": {},
	}
	for name, query in QUERIES.items():
		plan = runner.sql(f"EXPLAIN FORMAT=JSON {query};", database=True)
		result["queries"][name] = json.loads(plan)
	return result


def drop(runner: Runner, confirmation: str | None) -> dict[str, Any]:
	if confirmation != runner.database:
		raise RuntimeError(f"drop için --confirm-drop {runner.database} zorunlu")
	existed = runner.exists()
	if existed:
		runner.sql(f"DROP DATABASE `{runner.database}`;")
	return {"database": runner.database, "dropped": existed, "recreate": "prepare + seed-* + indexes"}


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"command",
		choices=("prepare", "seed-assets", "seed-renditions", "indexes", "counts", "explain", "all", "drop"),
	)
	parser.add_argument("--database", default=DEFAULT_DATABASE)
	parser.add_argument("--container", default=DEFAULT_CONTAINER)
	parser.add_argument("--confirm-drop")
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	if not DATABASE_RE.fullmatch(args.database):
		raise SystemExit("database adı media_phase4_bench_ öneki ve küçük harf/rakam/_ taşımalı")
	runner = Runner(args.container, args.database)
	operations = {
		"prepare": lambda: prepare(runner),
		"seed-assets": lambda: seed_assets(runner),
		"seed-renditions": lambda: seed_renditions(runner),
		"indexes": lambda: install_indexes(runner),
		"counts": lambda: counts(runner),
		"explain": lambda: explain(runner),
		"drop": lambda: drop(runner, args.confirm_drop),
	}
	try:
		if args.command == "all":
			result = {
				name: _phase(name, operations[name])
				for name in ("prepare", "seed-assets", "seed-renditions", "indexes", "explain")
			}
		else:
			result = _phase(args.command, operations[args.command])
	except (RuntimeError, subprocess.SubprocessError) as exc:
		print(f"HATA: {exc}", file=sys.stderr)
		return 1
	print(json.dumps({"database": args.database, "command": args.command, "result": result}, ensure_ascii=False, indent=2))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
