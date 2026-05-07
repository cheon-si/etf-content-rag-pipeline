"""Pipeline orchestration function signatures."""

from __future__ import annotations

import logging
from typing import Any

from app.config.settings import load_settings
from app.filtering.rule_filter import apply_rule_filter_to_rows
from app.filtering.scorer import attach_proxy_scores
from app.ingestion.naver_blog import collect_blog_posts
from app.preprocessing.cleaner import enrich_document_fields
from app.preprocessing.extractor import extract_blog_content
from app.storage.csv_store import save_csv
from app.storage.json_store import save_json

logger = logging.getLogger(__name__)
_DEFAULT_MIN_LENGTH = 150
_DEFAULT_PROXY_THRESHOLD = 0.2


def run_collection() -> list[dict[str, Any]]:
    """Run collection stage and return raw rows."""
    logger.info("Collection stage started.")
    settings_map = load_settings()

    keywords = list(settings_map["DEFAULT_KEYWORDS"])
    days = int(settings_map["DEFAULT_DAYS"])
    max_per_keyword = int(settings_map["MAX_RESULTS_PER_KEYWORD"])
    min_per_keyword = int(settings_map["MIN_RESULTS_PER_KEYWORD"])

    rows = collect_blog_posts(
        keywords=keywords,
        days=days,
        max_per_keyword=max_per_keyword,
    )

    save_csv(rows, "data/raw/collected_blog_posts.csv")
    save_json(rows, "data/raw/collected_blog_posts.json")

    expected_min_total = len(keywords) * min_per_keyword
    if len(rows) < expected_min_total:
        logger.warning(
            "Collection result is below expected minimum (actual=%d, expected_min=%d)",
            len(rows),
            expected_min_total,
        )

    logger.info("Collection stage completed (rows=%d).", len(rows))
    return rows


def run_preprocessing(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run preprocessing stage and return updated rows."""
    logger.info("Preprocessing stage started (rows=%d).", len(rows))
    rows_with_raw: list[dict[str, Any]] = []

    for idx, row in enumerate(rows):
        updated_row = dict(row)
        link = str(updated_row.get("link", "")).strip()
        raw_text = extract_blog_content(link) if link else ""
        updated_row["raw_text"] = raw_text
        rows_with_raw.append(updated_row)

        if (idx + 1) % 50 == 0:
            logger.info("Preprocessing extraction progress: %d/%d", idx + 1, len(rows))

    preprocessed_rows = enrich_document_fields(rows_with_raw)
    save_csv(preprocessed_rows, "data/interim/preprocessed_docs.csv")
    save_json(preprocessed_rows, "data/interim/preprocessed_docs.json")

    logger.info("Preprocessing stage completed (rows=%d).", len(preprocessed_rows))
    return preprocessed_rows


def run_filtering(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run filtering stage and return filtered/scored rows."""
    logger.info("Filtering stage started (rows=%d).", len(rows))
    rule_filtered_rows = apply_rule_filter_to_rows(rows, min_length=_DEFAULT_MIN_LENGTH)
    scored_rows = attach_proxy_scores(rule_filtered_rows)

    final_rows = [
        row
        for row in scored_rows
        if bool(row.get("passed_rule_filter")) and float(row.get("proxy_score", 0.0)) >= _DEFAULT_PROXY_THRESHOLD
    ]

    save_csv(scored_rows, "data/processed/scored_docs.csv")
    save_json(scored_rows, "data/processed/scored_docs.json")
    save_csv(final_rows, "data/processed/filtered_docs.csv")
    save_json(final_rows, "data/processed/filtered_docs.json")

    logger.info(
        "Filtering stage completed (input=%d, scored=%d, final=%d, proxy_threshold=%.2f).",
        len(rows),
        len(scored_rows),
        len(final_rows),
        _DEFAULT_PROXY_THRESHOLD,
    )
    return final_rows


def run_pipeline() -> list[dict[str, Any]]:
    """Run implemented pipeline stages (collection, preprocessing, filtering)."""
    logger.info("Pipeline execution started.")

    rows = run_collection()
    rows = run_preprocessing(rows)
    rows = run_filtering(rows)
    logger.info("Pipeline execution completed (rows=%d).", len(rows))
    return rows
