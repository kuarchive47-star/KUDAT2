#!/usr/bin/env python3
"""정제 기사에서 엔티티/멘션/관계를 로컬 규칙으로 추출한다.

사전 및 기자명은 승인(approved), 본문 직책 패턴은 검수 대기(pending)로 둔다.
기사 원문을 외부 AI 서비스로 전송하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path


ENTITY_NS = uuid.UUID("ad55489f-11bf-4213-a9f9-fea930991087")
ALIAS_NS = uuid.UUID("e6adf2d6-b8c0-4695-8490-bcbd91377f85")
MENTION_NS = uuid.UUID("ae912301-cf3a-4d4f-9138-af7af4f239db")
RELATION_NS = uuid.UUID("56156f9b-90b8-49b2-8e93-b12bd400a9ea")
VERSION = "kudat-local-rules-v1"
ROLE_RE = re.compile(
    r"(?<![가-힣])(?P<name>[김이박최정강조윤장임한오서신권황안송류유홍전고문양손배백허남심노하곽성차주우구민진지엄채원천방공현함변염여추도소석선설마길연위표명기반라왕금옥육인맹제모탁국어은편용][가-힣]{1,3})(?:\([^\n)]{1,50}\))?\s+"
    r"(?:(?P<affiliation>[가-힣A-Za-z0-9·&.\-]{1,30})\s*)?"
    r"(?P<role>총장|부총장|처장|과장|부장|회장|위원장|교수|연구원|대표|국장|팀장|학장|원장|소장|의원|장관|총재|감독)"
    r"(?:은|는|이|가|에게|의|을|를|도|으로|라고|이라며|께서)"
)
BYLINE_RE = re.compile(r"([가-힣]{2,4})\s*(?:수습|전문)?기자")


def normalize_name(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (value or "").lower())


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def entity_id(kind: str, canonical_name: str) -> str:
    return str(uuid.uuid5(ENTITY_NS, f"{kind}|{normalize_name(canonical_name)}"))


def evidence_window(text: str, start: int, end: int, radius: int = 80) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - radius): min(len(text), end + radius)]).strip()


def paragraph_number(text: str, offset: int) -> int:
    return text[:offset].count("\n\n") + 1


def add_entity(store: dict, kind: str, name: str, confidence: float, method: str,
               status: str, description: str | None = None, metadata: dict | None = None) -> str:
    canonical = re.sub(r"\s+", " ", name).strip()
    key = (kind, normalize_name(canonical))
    identifier = entity_id(kind, canonical)
    candidate = {
        "id": identifier,
        "kind": kind,
        "canonical_name": canonical,
        "normalized_name": key[1],
        "description": description,
        "metadata": metadata or {},
        "confidence": confidence,
        "extraction_method": method,
        "review_status": status,
    }
    existing = store.get(key)
    if not existing or confidence > existing["confidence"] or status == "approved":
        store[key] = candidate
    return identifier


def add_mention(store: dict, article_id: int, eid: str, surface: str, start: int, end: int,
                text: str, confidence: float, method: str, status: str) -> None:
    key = (article_id, eid, start, end)
    if key in store:
        return
    store[key] = {
        "id": str(uuid.uuid5(MENTION_NS, "|".join(map(str, key)))),
        "article_id": article_id,
        "entity_id": eid,
        "surface_text": surface,
        "paragraph_number": paragraph_number(text, start),
        "start_offset": start,
        "end_offset": end,
        "evidence_text": evidence_window(text, start, end),
        "confidence": confidence,
        "extraction_method": method,
        "extractor_version": VERSION,
        "review_status": status,
    }


def add_relation(store: dict, subject: str, predicate: str, obj: str, article_id: int,
                 evidence: str, confidence: float, method: str, status: str) -> None:
    if subject == obj:
        return
    key = f"{subject}|{predicate}|{obj}|{article_id}|{method}"
    identifier = str(uuid.uuid5(RELATION_NS, key))
    store[identifier] = {
        "id": identifier,
        "subject_entity_id": subject,
        "predicate": predicate,
        "object_entity_id": obj,
        "source_article_id": article_id,
        "evidence_text": evidence,
        "confidence": confidence,
        "extraction_method": method,
        "extractor_version": VERSION,
        "review_status": status,
        "valid_from": None,
        "valid_to": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--dictionary", type=Path, default=Path(__file__).parents[1] / "data/entity_dictionary.json")
    args = parser.parse_args()

    articles = read_jsonl(args.input_dir / "articles.jsonl")
    if not articles:
        parser.error("articles.jsonl이 없거나 비어 있습니다. prepare_articles.py를 먼저 실행하세요.")
    dictionary = json.loads(args.dictionary.read_text(encoding="utf-8"))["entities"]

    entities: dict[tuple[str, str], dict] = {}
    aliases: dict[tuple[str, str], dict] = {}
    mentions: dict[tuple, dict] = {}
    relations: dict[str, dict] = {}
    alias_entries: list[tuple[str, str, str, int]] = []

    for item in dictionary:
        eid = add_entity(
            entities, item["kind"], item["canonical_name"], 0.99,
            "curated_dictionary", "approved", "운영 사전에 등록된 엔터티"
        )
        names = sorted(set(item.get("aliases", []) + [item["canonical_name"]]), key=len, reverse=True)
        for alias in names:
            normalized = normalize_name(alias)
            alias_key = (eid, normalized)
            aliases[alias_key] = {
                "id": str(uuid.uuid5(ALIAS_NS, f"{eid}|{normalized}")),
                "entity_id": eid,
                "alias": alias,
                "normalized_alias": normalized,
            }
            alias_entries.append((alias, eid, item["kind"], len(alias)))

    alias_entries.sort(key=lambda row: row[3], reverse=True)
    newsroom_id = entity_id("organization", "고대신문사")
    stats = Counter()
    enriched_articles = []

    for article in articles:
        article_id = article["id"]
        text = article.get("body_text") or ""
        occupied: list[tuple[int, int]] = []
        article_entity_names: set[str] = set()

        # 긴 별칭부터 매칭하여 '본관 앞'과 '본관' 같은 중첩 멘션의 이중 집계를 막는다.
        for alias, eid, _kind, _length in alias_entries:
            for match in re.finditer(re.escape(alias), text, flags=re.IGNORECASE):
                span = match.span()
                if any(span[0] < end and start < span[1] for start, end in occupied):
                    continue
                add_mention(mentions, article_id, eid, match.group(), span[0], span[1], text,
                            0.99, "curated_dictionary", "approved")
                occupied.append(span)
                article_entity_names.add(next(e["canonical_name"] for e in entities.values() if e["id"] == eid))
                stats["dictionary_mentions"] += 1

        author_value = article.get("author_name") or ""
        if normalize_name(author_value) in {"고대신문", "고대신문사", "본보"}:
            add_mention(mentions, article_id, newsroom_id, author_value, 0, 0, text,
                        0.99, "source_byline", "approved")
            article_entity_names.add("고대신문사")
        else:
            byline_names = BYLINE_RE.findall(author_value)
            for name in dict.fromkeys(byline_names):
                pid = add_entity(
                    entities, "person", name, 0.99, "source_byline", "approved",
                    "기사 기자명 필드에서 확인된 인물", {"role": "기자"}
                )
                add_mention(mentions, article_id, pid, name, 0, 0, text,
                            0.99, "source_byline", "approved")
                add_relation(relations, pid, "affiliated_with", newsroom_id, article_id,
                             f"기자명: {author_value}", 0.99, "source_byline", "approved")
                article_entity_names.add(name)
                article_entity_names.add("고대신문사")
                stats["byline_people"] += 1

        # 직책 바로 앞의 한국인명 후보. 운영자가 CSV에서 승인해야 공개 그래프에 나타난다.
        for match in ROLE_RE.finditer(text):
            name, role = match.group("name"), match.group("role")
            if name in {"학교", "학생", "한국", "고려", "이번", "관련", "해당", "지난", "올해"}:
                continue
            pid = add_entity(
                entities, "person", name, 0.88, "role_pattern", "pending",
                "본문 직책 패턴으로 추정된 인물", {"role": role}
            )
            start, end = match.start("name"), match.end("name")
            add_mention(mentions, article_id, pid, name, start, end, text,
                        0.88, "role_pattern", "pending")
            stats["pending_role_people"] += 1

        enriched = dict(article)
        enriched["entity_search_text"] = " ".join(sorted(article_entity_names))
        enriched_articles.append(enriched)

    entity_rows = sorted(entities.values(), key=lambda row: (row["kind"], row["normalized_name"]))
    alias_rows = sorted(aliases.values(), key=lambda row: (row["entity_id"], row["normalized_alias"]))
    mention_rows = sorted(mentions.values(), key=lambda row: (row["article_id"], row["start_offset"], row["entity_id"]))
    relation_rows = sorted(relations.values(), key=lambda row: row["id"])

    write_jsonl(args.input_dir / "articles_enriched.jsonl", enriched_articles)
    write_jsonl(args.input_dir / "entities.jsonl", entity_rows)
    write_jsonl(args.input_dir / "entity_aliases.jsonl", alias_rows)
    write_jsonl(args.input_dir / "article_entity_mentions.jsonl", mention_rows)
    write_jsonl(args.input_dir / "entity_relations.jsonl", relation_rows)

    mention_counts = Counter(row["entity_id"] for row in mention_rows)
    with (args.input_dir / "entity_review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "id", "kind", "canonical_name", "review_status", "confidence",
            "mention_count", "description", "metadata_json", "review_note"
        ])
        writer.writeheader()
        for row in entity_rows:
            writer.writerow({
                "id": row["id"], "kind": row["kind"], "canonical_name": row["canonical_name"],
                "review_status": row["review_status"], "confidence": row["confidence"],
                "mention_count": mention_counts[row["id"]], "description": row.get("description") or "",
                "metadata_json": json.dumps(row.get("metadata", {}), ensure_ascii=False), "review_note": ""
            })

    report = {
        "article_count": len(articles),
        "entity_count": len(entity_rows),
        "approved_entity_count": sum(row["review_status"] == "approved" for row in entity_rows),
        "pending_entity_count": sum(row["review_status"] == "pending" for row in entity_rows),
        "alias_count": len(alias_rows),
        "mention_count": len(mention_rows),
        "approved_mention_count": sum(row["review_status"] == "approved" for row in mention_rows),
        "relation_count": len(relation_rows),
        "stats": dict(stats),
        "extractor_version": VERSION,
        "external_ai_used": False,
    }
    (args.input_dir / "entity_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
