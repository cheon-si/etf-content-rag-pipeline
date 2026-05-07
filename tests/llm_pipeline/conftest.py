"""공통 픽스처."""
from __future__ import annotations

import pytest

from llm_pipeline.schemas import ClusterInput

SAMPLE_HTML = """<!DOCTYPE html>
<html><body>
<div class="section">
  <h2>4. K-Means 클러스터 분석</h2>
  <p>best k=5</p>
  <table style="margin-top:20px">
    <thead>
      <tr>
        <th width="80">클러스터</th>
        <th width="80">포스트 수</th>
        <th>대표 키워드 (상위 10개)</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td style="text-align:center;font-weight:bold">미국테크/AI/반도체</td>
        <td style="text-align:center">320</td>
        <td>
          <span>미국테크</span><span>AI</span><span>반도체</span>
          <span>나스닥</span><span>QQQ</span><span>엔비디아</span>
          <span>성장주</span><span>기술주</span><span>레버리지</span><span>인버스</span>
        </td>
      </tr>
      <tr>
        <td style="text-align:center;font-weight:bold">채권/금리/안전자산</td>
        <td style="text-align:center">180</td>
        <td>
          <span>채권ETF</span><span>금리</span><span>안전자산</span>
          <span>미국채</span><span>TLT</span><span>월배당</span>
          <span>커버드콜</span><span>분산</span><span>채권</span><span>국채</span>
        </td>
      </tr>
      <tr>
        <td style="text-align:center;font-weight:bold">배당/월배당/커버드콜</td>
        <td style="text-align:center">95</td>
        <td>
          <span>월배당</span><span>커버드콜</span><span>배당ETF</span>
          <span>JEPI</span><span>QYLD</span><span>배당주</span>
          <span>현금흐름</span><span>노후</span><span>은퇴</span><span>연금</span>
        </td>
      </tr>
      <tr style="opacity:0.75">
        <td style="text-align:center;font-weight:bold">인도/베트남/신흥국<span>소규모</span></td>
        <td style="text-align:center">8</td>
        <td>
          <span>인도ETF</span><span>베트남</span><span>신흥국</span>
          <span>이머징</span><span>아세안</span>
        </td>
      </tr>
    </tbody>
  </table>
  <details>
    <summary>▶ 분석 제외 클러스터 보기 (노이즈)</summary>
    <table>
      <thead>
        <tr><th>클러스터</th><th>포스트 수</th><th>키워드</th></tr>
      </thead>
      <tbody>
        <tr style="color:#aaa">
          <td>naver/blog/com</td>
          <td>50</td>
          <td><span>naver</span><span>blog</span><span>com</span></td>
        </tr>
      </tbody>
    </table>
  </details>
</div>
</body></html>"""


@pytest.fixture
def sample_html_path(tmp_path):
    p = tmp_path / "etf_trend_report.html"
    p.write_text(SAMPLE_HTML, encoding="utf-8")
    return p


@pytest.fixture
def sample_cluster() -> ClusterInput:
    return ClusterInput(
        rank=1,
        cluster_name="미국테크/AI/반도체",
        keywords=["미국테크", "AI", "반도체", "나스닥", "QQQ", "엔비디아", "성장주", "기술주", "레버리지", "인버스"],
        post_count=320,
    )
