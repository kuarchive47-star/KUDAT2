#!/usr/bin/env python3
"""entity_review.csv의 승인/거절 결과를 JSONL 전체에 반영한다."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


VALID = {"pending", "approved", "rejected"}


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--review-csv", type=Path)
    args = parser.parse_args()
    review_path = args.review_csv or args.input_dir / "entity_review.csv"

    with review_path.open(encoding="utf-8-sig", newline="") as handle:
        reviews = {row["id"]: row["review_status"].strip().lower() for row in csv.DictReader(handle)}
    invalid = sorted({status for status in reviews.values() if status not in VALID})
    if invalid:
        raise SystemExit(f"허용되지 않은 review_status: {', '.join(invalid)}")

    entities = read_jsonl(args.input_dir / "entities.jsonl")
    for row in entities:
        if row["id"] in reviews:
            row["review_status"] = reviews[row["id"]]
    statuses = {row["id"]: row["review_status"] for row in entities}

    mentions = read_jsonl(args.input_dir / "article_entity_mentions.jsonl")
    for row in mentions:
        row["review_status"] = statuses.get(row["entity_id"], row["review_status"])

    relations = read_jsonl(args.input_dir / "entity_relations.jsonl")
    for row in relations:
        endpoint_statuses = {statuses.get(row["subject_entity_id"]), statuses.get(row["object_entity_id"])}
        if "rejected" in endpoint_statuses:
            row["review_status"] = "rejected"
        elif endpoint_statuses == {"approved"}:
            row["review_status"] = "approved"
        else:
            row["review_status"] = "pending"

    write_jsonl(args.input_dir / "entities.jsonl", entities)
    write_jsonl(args.input_dir / "article_entity_mentions.jsonl", mentions)
    write_jsonl(args.input_dir / "entity_relations.jsonl", relations)
    print(json.dumps({
        "entities": len(entities),
        "approved": sum(row["review_status"] == "approved" for row in entities),
        "pending": sum(row["review_status"] == "pending" for row in entities),
        "rejected": sum(row["review_status"] == "rejected" for row in entities),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
