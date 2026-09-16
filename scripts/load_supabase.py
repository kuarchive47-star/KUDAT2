#!/usr/bin/env python3
"""준비된 JSONL을 Supabase PostgREST에 배치 upsert한다."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


LOAD_ORDER = [
    ("articles", ("articles_enriched.jsonl", "articles.jsonl")),
    ("article_media", ("article_media.jsonl",)),
    ("entities", ("entities.jsonl",)),
    ("entity_aliases", ("entity_aliases.jsonl",)),
    ("article_entity_mentions", ("article_entity_mentions.jsonl",)),
    ("entity_relations", ("entity_relations.jsonl",)),
]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip("'\""))


def select_file(directory: Path, candidates: tuple[str, ...]) -> Path | None:
    return next((directory / name for name in candidates if (directory / name).exists()), None)


def iter_batches(path: Path, size: int):
    batch = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                batch.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number} JSON 오류: {exc}") from exc
            if len(batch) >= size:
                yield batch
                batch = []
    if batch:
        yield batch


def post_batch(base_url: str, key: str, table: str, records: list[dict], timeout: int) -> None:
    query = urlencode({"on_conflict": "id"})
    url = f"{base_url.rstrip('/')}/rest/v1/{table}?{query}"
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "apikey": key,
        "Content-Type": "application/json; charset=utf-8",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    # 새 sb_secret 키는 apikey 헤더만 사용한다. JWT 형식의 legacy service_role만
    # Authorization 헤더를 함께 보낸다.
    if key.count(".") == 2:
        headers["Authorization"] = f"Bearer {key}"
    request = Request(url, data=payload, method="POST", headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status not in {200, 201, 204}:
                raise RuntimeError(f"{table}: HTTP {response.status}")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"{table}: HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{table}: 네트워크 오류: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).parents[1] / ".env")
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 500:
        parser.error("--batch-size는 1~500이어야 합니다.")

    load_env_file(args.env_file)
    base_url = os.environ.get("SUPABASE_URL", "").strip()
    secret_key = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not args.dry_run and (not base_url or not secret_key):
        parser.error("SUPABASE_URL과 SUPABASE_SECRET_KEY 환경변수가 필요합니다.")

    summary = {}
    for table, candidates in LOAD_ORDER:
        path = select_file(args.input_dir, candidates)
        if path is None:
            summary[table] = {"file": None, "rows": 0, "status": "skipped"}
            continue
        total = 0
        for batch_number, batch in enumerate(iter_batches(path, args.batch_size), start=1):
            if not args.dry_run:
                post_batch(base_url, secret_key, table, batch, args.timeout)
            total += len(batch)
            print(f"{table}: {total}행 {'확인' if args.dry_run else '적재'}", file=sys.stderr)
        summary[table] = {"file": path.name, "rows": total, "status": "dry-run" if args.dry_run else "loaded"}

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
