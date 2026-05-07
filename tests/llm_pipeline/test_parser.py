"""parser.py 단위 테스트."""
from __future__ import annotations

import pytest

from llm_pipeline.parser import list_clusters, parse_clusters
from llm_pipeline.schemas import ClusterInput


class TestParseTopClusters:
    def test_default_top3(self, sample_html_path):
        clusters = parse_clusters(sample_html_path)
        assert len(clusters) == 3

    def test_sorted_by_post_count(self, sample_html_path):
        clusters = parse_clusters(sample_html_path)
        counts = [c.post_count for c in clusters]
        assert counts == sorted(counts, reverse=True)

    def test_ranks_assigned_correctly(self, sample_html_path):
        clusters = parse_clusters(sample_html_path)
        assert [c.rank for c in clusters] == [1, 2, 3]

    def test_top1_is_largest_cluster(self, sample_html_path):
        clusters = parse_clusters(sample_html_path)
        assert clusters[0].cluster_name == "미국테크/AI/반도체"
        assert clusters[0].post_count == 320

    def test_keywords_extracted(self, sample_html_path):
        clusters = parse_clusters(sample_html_path)
        assert "AI" in clusters[0].keywords
        assert len(clusters[0].keywords) == 10

    def test_noise_cluster_excluded(self, sample_html_path):
        clusters = parse_clusters(sample_html_path)
        names = [c.cluster_name for c in clusters]
        assert not any("naver" in n.lower() for n in names)

    def test_small_badge_stripped_from_name(self, sample_html_path):
        clusters = parse_clusters(sample_html_path, top_n=4)
        names = [c.cluster_name for c in clusters]
        assert not any("소규모" in n for n in names)


class TestClusterSelection:
    def test_select_by_index(self, sample_html_path):
        clusters = parse_clusters(sample_html_path, spec="1,3")
        assert len(clusters) == 2
        # 테이블 순서 1번=미국테크, 3번=배당
        assert "미국테크" in clusters[0].cluster_name
        assert "배당" in clusters[1].cluster_name

    def test_select_by_name(self, sample_html_path):
        clusters = parse_clusters(sample_html_path, spec="채권")
        assert len(clusters) == 1
        assert "채권" in clusters[0].cluster_name

    def test_select_multiple_names(self, sample_html_path):
        clusters = parse_clusters(sample_html_path, spec="미국테크,배당")
        assert len(clusters) == 2

    def test_top_n_respected(self, sample_html_path):
        clusters = parse_clusters(sample_html_path, top_n=2)
        assert len(clusters) == 2


class TestListClusters:
    def test_returns_all_non_noise(self, sample_html_path):
        clusters = list_clusters(sample_html_path)
        # 노이즈(details) 제외 4개
        assert len(clusters) == 4

    def test_sorted_by_post_count(self, sample_html_path):
        clusters = list_clusters(sample_html_path)
        counts = [c.post_count for c in clusters]
        assert counts == sorted(counts, reverse=True)


class TestEdgeCases:
    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_clusters(tmp_path / "nonexistent.html")

    def test_no_kmeans_section(self, tmp_path):
        bad_html = "<html><body><h2>다른 섹션</h2></body></html>"
        p = tmp_path / "bad.html"
        p.write_text(bad_html, encoding="utf-8")
        with pytest.raises(ValueError, match="K-Means"):
            parse_clusters(p)
