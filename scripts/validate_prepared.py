#!/usr/bin/env python3
"""Supabase 적재 전 구조·참조·HTML 안전성 검증."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from lxml import html


FORBIDDEN_TAGS = {"script", "style", "iframe", "img", "form", "object", "embed", "svg", "math"}
NETWORK_ATTRIBUTES = {"href", "src", "srcset", "poster", "action"}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    args = parser.parse_args()
    directory = args.input_dir
    article_path = directory / "articles_enriched.jsonl"
    if not article_path.exists():
        article_path = directory / "articles.jsonl"

    articles = read_jsonl(article_path)
    media = read_jsonl(directory / "article_media.jsonl")
    entities = read_jsonl(directory / "entities.jsonl")
    aliases = read_jsonl(directory / "entity_aliases.jsonl")
    mentions = read_jsonl(directory / "article_entity_mentions.jsonl")
    relations = read_jsonl(directory / "entity_relations.jsonl")
    errors: list[str] = []

    article_ids = [row.get("id") for row in articles]
    entity_ids = [row.get("id") for row in entities]
    if len(article_ids) != len(set(article_ids)):
        errors.append("articles.id 중복")
    if len(entity_ids) != len(set(entity_ids)):
        errors.append("entities.id 중복")
    article_set, entity_set = set(article_ids), set(entity_ids)
    record_keys = [row.get("source_record_key") for row in articles]
    if len(record_keys) != len(set(record_keys)):
        errors.append("articles.source_record_key 중복")

    for row in articles:
        prefix = f"article {row.get('id')}"
        if not row.get("title") or not row.get("published_on"):
            errors.append(f"{prefix}: 제목 또는 발행일 누락")
        expected_key = f"xlsx:Sheet1:{row.get('id')}"
        if row.get("source_record_key") != expected_key:
            errors.append(f"{prefix}: XLSX 레코드 키 오류")
        if "source_url" in row or "hero_image_url" in row:
            errors.append(f"{prefix}: 외부 접근용 URL 필드가 남아 있음")
        try:
            wrapper = html.fragment_fromstring(row.get("body_html") or "", create_parent="div")
        except Exception as exc:
            errors.append(f"{prefix}: HTML 파싱 오류 {exc}")
            continue
        for element in wrapper.iterdescendants():
            tag = element.tag.lower() if isinstance(element.tag, str) else ""
            if tag in FORBIDDEN_TAGS:
                errors.append(f"{prefix}: 금지 태그 <{tag}>")
            for attribute, value in element.attrib.items():
                if attribute.lower().startswith("on") or attribute.lower() == "style":
                    errors.append(f"{prefix}: 금지 속성 {attribute}")
                if attribute.lower() in NETWORK_ATTRIBUTES:
                    errors.append(f"{prefix}: 외부 접근 가능 속성 {attribute}")

    for row in media:
        if row.get("article_id") not in article_set:
            errors.append(f"media {row.get('id')}: 없는 article_id")
        if not row.get("source_path"):
            errors.append(f"media {row.get('id')}: XLSX 원본 경로 누락")
        if "source_url" in row:
            errors.append(f"media {row.get('id')}: 외부 접근용 URL 필드가 남아 있음")
    for row in aliases:
        if row.get("entity_id") not in entity_set:
            errors.append(f"alias {row.get('id')}: 없는 entity_id")
    for row in mentions:
        if row.get("article_id") not in article_set or row.get("entity_id") not in entity_set:
            errors.append(f"mention {row.get('id')}: 참조 오류")
        if row.get("review_status") not in {"pending", "approved", "rejected"}:
            errors.append(f"mention {row.get('id')}: review_status 오류")
    for row in relations:
        if row.get("subject_entity_id") not in entity_set or row.get("object_entity_id") not in entity_set:
            errors.append(f"relation {row.get('id')}: 엔터티 참조 오류")
        if row.get("source_article_id") not in article_set:
            errors.append(f"relation {row.get('id')}: 기사 참조 오류")

    report = {
        "valid": not errors,
        "source_mode": "xlsx_only",
        "external_article_link_fields": sum(
            int("source_url" in row or "hero_image_url" in row) for row in articles
        ),
        "counts": {
            "articles": len(articles), "article_media": len(media), "entities": len(entities),
            "entity_aliases": len(aliases), "mentions": len(mentions), "relations": len(relations),
            "public_articles": sum(bool(row.get("is_public")) for row in articles),
        },
        "entity_review_status": dict(Counter(row.get("review_status") for row in entities)),
        "errors": errors[:100],
        "error_count": len(errors),
    }
    (directory / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
