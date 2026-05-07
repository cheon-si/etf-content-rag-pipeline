"""HTML 리포트 → 클러스터 목록 파싱 및 선택."""
from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from llm_pipeline.config import NOISE_KEYWORDS
from llm_pipeline.schemas import ClusterInput, ClusterRaw

_NOISE_KWS = NOISE_KEYWORDS


def _parse_all_clusters(soup: BeautifulSoup) -> list[ClusterRaw]:
    """메인 클러스터 테이블(노이즈 제외)에서 전체 클러스터를 파싱한다."""
    # "K-Means" 포함 h2 섹션 탐색
    target_section: Tag | None = None
    for h2 in soup.find_all("h2"):
        if "K-Means" in h2.get_text():
            # h2의 부모 div.section 또는 h2 이후 형제 요소 탐색
            target_section = h2.find_parent("div") or h2.parent
            break

    if target_section is None:
        raise ValueError("HTML 리포트에서 K-Means 클러스터 섹션을 찾을 수 없습니다.")

    # <details> 내 노이즈 테이블 제거 후 메인 테이블 탐색
    details_tags = target_section.find_all("details")
    for d in details_tags:
        d.decompose()

    main_table: Tag | None = None
    for table in target_section.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if any("포스트 수" in h for h in headers):
            main_table = table
            break

    if main_table is None:
        raise ValueError("K-Means 섹션에서 클러스터 테이블을 찾을 수 없습니다.")

    clusters: list[ClusterRaw] = []
    tbody = main_table.find("tbody")
    rows = tbody.find_all("tr") if tbody else []

    for idx, row in enumerate(rows):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        name_cell = cells[0].get_text(separator=" ", strip=True)
        # 링크 텍스트·배지 제거: 📋, 소규모 등
        cluster_name = re.sub(r"[📋]|소규모", "", name_cell).strip()

        try:
            post_count = int(cells[1].get_text(strip=True).replace(",", ""))
        except ValueError:
            post_count = 0

        keywords = [
            span.get_text(strip=True)
            for span in cells[2].find_all("span")
            if span.get_text(strip=True)
        ]

        clusters.append(ClusterRaw(
            table_index=idx,
            cluster_name=cluster_name,
            post_count=post_count,
            keywords=keywords,
        ))

    return clusters


def _select_clusters(
    all_clusters: list[ClusterRaw],
    spec: str | None,
    top_n: int,
) -> list[ClusterInput]:
    """spec에 따라 클러스터를 선택하고 ClusterInput 목록을 반환한다."""
    if spec is None:
        # 포스트 수 기준 상위 top_n
        selected = sorted(all_clusters, key=lambda c: c.post_count, reverse=True)[:top_n]
        selected = sorted(selected, key=lambda c: c.post_count, reverse=True)
    elif re.match(r"^[\d,\s]+$", spec):
        # 숫자 인덱스 (1-based 테이블 순서)
        indices = [int(i.strip()) - 1 for i in spec.split(",") if i.strip()]
        selected = [c for c in all_clusters if c.table_index in indices]
        selected = sorted(selected, key=lambda c: indices.index(c.table_index))
    else:
        # 클러스터명 부분 일치
        names = [n.strip() for n in spec.split(",")]
        selected = []
        for name in names:
            for c in all_clusters:
                if name in c.cluster_name and c not in selected:
                    selected.append(c)
                    break

    return [
        ClusterInput(
            rank=rank,
            cluster_name=c.cluster_name,
            keywords=c.keywords,
            post_count=c.post_count,
        )
        for rank, c in enumerate(selected, start=1)
    ]


def parse_clusters(
    report_path: str | Path,
    spec: str | None = None,
    top_n: int = 3,
) -> list[ClusterInput]:
    """HTML 리포트를 파싱하여 선택된 클러스터 목록을 반환한다.

    Args:
        report_path: HTML 리포트 파일 경로.
        spec: 클러스터 선택 지정자.
              None → 포스트 수 상위 top_n개 자동 선택.
              "1,3" → 테이블 순서 기준 1번·3번 클러스터 (1-based).
              "미국테크/AI,채권ETF" → 클러스터명 부분 일치 검색.
        top_n: spec=None 시 선택할 클러스터 수.
    """
    html = Path(report_path).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    all_clusters = _parse_all_clusters(soup)
    return _select_clusters(all_clusters, spec, top_n)


def list_clusters(report_path: str | Path) -> list[ClusterRaw]:
    """리포트의 전체 클러스터 목록(노이즈 제외)을 반환한다."""
    html = Path(report_path).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    return sorted(_parse_all_clusters(soup), key=lambda c: c.post_count, reverse=True)
