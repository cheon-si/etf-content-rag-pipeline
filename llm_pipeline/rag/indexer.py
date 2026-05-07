"""배치 인덱서: 블로그/뉴스/과거 LLM 결과물 → FAISS 인덱스."""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from llm_pipeline.rag.vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = str(_PROJECT_ROOT / "etf_trend.db")
INDEX_DIR = str(_PROJECT_ROOT / "data" / "rag")


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        logger.warning("[Indexer] 파일 없음: %s", path)
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def index_blog_corpus(vs: VectorStore) -> int:
    path = _PROJECT_ROOT / "data" / "processed" / "filtered_docs.json"
    docs_raw = _load_json(path)
    if not docs_raw:
        return 0

    documents = []
    for d in docs_raw:
        doc_id = d.get("doc_id", hashlib.md5(d.get("link", "").encode()).hexdigest())
        documents.append({
            "doc_id": doc_id,
            "title": d.get("title", ""),
            "text": d.get("clean_text", d.get("description", "")),
            "post_date": d.get("post_date", ""),
            "metadata": {
                "proxy_score": d.get("proxy_score", 0),
                "etf_mentions": d.get("etf_mentions", 0),
                "keyword": d.get("keyword", ""),
            },
        })
    return vs.build_index("blog", documents)


def index_news_corpus(vs: VectorStore) -> int:
    candidates = [
        _PROJECT_ROOT / "data" / "processed" / "news_weekly_filtered.json",
        _PROJECT_ROOT / "data" / "processed" / "news_filtered_docs.json",
    ]
    docs_raw = []
    for path in candidates:
        docs_raw = _load_json(path)
        if docs_raw:
            break
    if not docs_raw:
        logger.info("[Indexer] 뉴스 데이터 없음, 건너뜀")
        return 0

    documents = []
    for d in docs_raw:
        doc_id = d.get("doc_id", hashlib.md5(d.get("link", "").encode()).hexdigest())
        documents.append({
            "doc_id": doc_id,
            "title": d.get("title", ""),
            "text": d.get("clean_text", d.get("description", "")),
            "post_date": d.get("post_date", ""),
            "metadata": {"keyword": d.get("keyword", "")},
        })
    return vs.build_index("news", documents)


def index_past_outputs(vs: VectorStore) -> int:
    output_dir = _PROJECT_ROOT / "output"
    if not output_dir.exists():
        return 0

    documents = []
    for date_dir in sorted(output_dir.iterdir()):
        if not date_dir.is_dir():
            continue
        ideas_path = date_dir / "content_ideas.json"
        if not ideas_path.exists():
            continue

        ideas = _load_json(ideas_path)
        for idea in ideas:
            cluster_name = idea.get("cluster_name", "")
            doc_id = f"{date_dir.name}_{cluster_name}"
            blog_titles = idea.get("blog_titles", [])
            one_liner = idea.get("one_liner", "")
            text = f"{cluster_name} {one_liner} {' '.join(blog_titles)}"

            documents.append({
                "doc_id": doc_id,
                "title": cluster_name,
                "text": text,
                "post_date": date_dir.name,
                "metadata": {
                    "keywords": idea.get("keywords", []),
                    "blog_titles": blog_titles,
                },
            })
    return vs.build_index("past_output", documents)


def main() -> None:
    vs = VectorStore(INDEX_DIR, DB_PATH)

    print("=" * 60)
    print("Vector RAG 인덱싱 시작")
    print("=" * 60)

    n_blog = index_blog_corpus(vs)
    n_news = index_news_corpus(vs)
    n_past = index_past_outputs(vs)

    print(f"\n완료:")
    print(f"  블로그: {n_blog}건 (총 {vs.collection_size('blog')}건)")
    print(f"  뉴스:   {n_news}건 (총 {vs.collection_size('news')}건)")
    print(f"  과거 결과물: {n_past}건 (총 {vs.collection_size('past_output')}건)")

    # 검증
    if vs.collection_size("blog") > 0:
        print("\n검색 테스트 - 'ETF':")
        for r in vs.search("ETF", "blog", top_k=3):
            print(f"  [{r['score']:.3f}] {r['title'][:50]}")


if __name__ == "__main__":
    main()
