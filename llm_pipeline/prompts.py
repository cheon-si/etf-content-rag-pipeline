"""LLM 파이프라인 프롬프트 템플릿 모음."""
from __future__ import annotations

PROMPT_S1 = """\
당신은 한국 ETF 투자자의 검색 행동을 분석하는 전문가입니다.

아래 ETF 클러스터의 이름과 대표 키워드를 보고, 이 키워드 조합을 검색하는 투자자의 주요 의도를
Informational / Commercial / Transactional 중 하나로 분류하세요.

클러스터명: {cluster_name}
대표 키워드 (상위 10개): {keywords}

다음 JSON 형식으로만 응답하세요:
{{
  "intent_type": "Informational" | "Commercial" | "Transactional",
  "confidence": 0.0~1.0,
  "reasoning": "왜 이 의도인지 2~3문장으로 한국어 설명"
}}

분류 기준:
- Informational: ETF 개념, 구조, 시장 동향 파악 목적
- Commercial: 특정 ETF 상품 비교·검토, 투자 결정 전 조사
- Transactional: 매수/매도 실행, 계좌 개설, 특정 ETF 종목 직접 탐색
"""

PROMPT_S2 = """\
당신은 Clayton Christensen의 JTBD(Jobs To Be Done) 프레임워크를 금융 투자 맥락에 적용하는 전문가입니다.

아래 ETF 클러스터에 관심을 갖는 투자자가 "진짜로 해결하려는 일(Job)"을 추출하세요.

클러스터명: {cluster_name}
대표 키워드: {keywords}
검색 의도: {intent_type} ({intent_reasoning})

다음 JSON 형식으로만 응답하세요:
{{
  "main_job": "투자자가 궁극적으로 달성하려는 한 가지 핵심 목표 (1문장)",
  "functional_needs": ["실용적 필요 3~5가지"],
  "emotional_needs": ["정서적 필요 3~5가지 (불안 해소, 자신감 등)"],
  "social_needs": ["사회적 필요 2~3가지 (동료/가족에게 인정받기 등)"],
  "hire_context": "이 콘텐츠를 '고용'하게 되는 구체적 상황 묘사 (2~3문장)"
}}

금융 투자 맥락을 충분히 반영하여 한국어로 응답하세요.
"""

PROMPT_S3_GEMINI = """\
아래 ETF 주제에 대해 현재 네이버 블로그와 구글 검색 상위 노출 콘텐츠의 공통 구조와 공백을 분석해주세요.

클러스터명: {cluster_name}
키워드: {keywords}
투자자의 핵심 Job: {main_job}

추가 조사 요청:
1. 이 주제와 관련된 국내 상장 ETF 상품명을 최대한 수집해주세요.
   (예: KODEX, TIGER, KBSTAR, HANARO, ARIRANG, TIMEFOLIO 등 운용사별 구체적 상품명과 종목코드)
2. 주요 ETF의 수익률, AUM(순자산), 총보수(TER) 등 수치 데이터를 포함해주세요.
3. 최근 시장 동향과 관련 뉴스 헤드라인을 2~3개 포함해주세요.

분석 결과를 다음 JSON 형식으로 제공하세요:
{{
  "top_content_patterns": ["상위 노출 콘텐츠가 공통적으로 다루는 패턴 3~5가지"],
  "content_gaps": ["상위 콘텐츠에서 빠진 공백 3~5가지"],
  "competitor_angles": ["경쟁 콘텐츠가 주로 취하는 각도 3가지"],
  "domestic_etf_products": ["관련 국내 상장 ETF 상품명 및 종목코드 목록"],
  "market_data": ["수익률/AUM/TER 등 수치 데이터 (출처 포함)"],
  "recent_news": ["최근 관련 뉴스 헤드라인 2~3개"]
}}
"""

PROMPT_S3_OPUS = """\
아래 조사 결과를 바탕으로 ETF 블로그 콘텐츠의 Pillar-Sub 구조를 설계하세요.

클러스터명: {cluster_name}
키워드: {keywords}
투자자 핵심 Job: {main_job}
기능적 니즈: {functional_needs}
검색 의도: {intent_type}
시장 조사 결과:
{market_research}

다음 JSON 형식으로만 응답하세요:
{{
  "pillar_title": "Pillar 콘텐츠 제목 (클릭욕구 유발, 한국어)",
  "pillar_angle": "Pillar 콘텐츠의 차별화 각도 (1~2문장)",
  "sub_topics": [
    {{
      "title": "Sub topic 제목",
      "angle": "이 sub topic만의 차별 관점",
      "keywords": ["타깃 키워드 3~5개"]
    }}
  ],
  "competitor_gaps": ["기존 콘텐츠 대비 이 구조가 채우는 공백 3가지"]
}}

sub_topics는 정확히 5개로 구성하세요.
"""

PROMPT_S4_DRAFT = """\
당신은 한국 ETF 금융 블로그 작가입니다. 아래 정보를 바탕으로 블로그 원고 초안을 작성하세요.

클러스터명: {cluster_name}
Pillar 제목: {pillar_title}
Pillar 각도: {pillar_angle}
투자자 핵심 Job: {main_job}
기능적 니즈: {functional_needs}
독자 상황 (감성적 도입부 참고): {hire_context}

작성 요구사항:
- 도입부: hire_context를 반영해 독자 상황에 공감하는 감성적 첫 문단으로 시작 (2~3문장)
- AIDA(Attention-Interest-Desire-Action) 또는 PAS(Problem-Agitation-Solution) 프레임워크 적용
- 목표 분량: 2,000자 이상 (최대 3,000자)
- H2 최소 3개, H3 적절히 배치
- FAQ 섹션 3개 이상 (GEO 최적화용)
- 출처 링크 placeholder [출처: XXX] 삽입 (구체적 상품명·수치 직후 반드시 삽입)
- 투자 권유가 아닌 정보 제공 톤 유지 (금융 컴플라이언스)
- 문장당 40자 이내 권장
- 이미지 삽입이 적절한 위치에 [이미지: 설명] placeholder 추가 (예: [이미지: ETF 수익률 비교표])
- 국내 상장 ETF 상품명(KODEX/TIGER 등)은 구체적 상품명과 종목코드를 함께 기재
- CTA(Call to Action) 문구: 마무리 섹션에 "[더 알아보기: 관련 콘텐츠 링크]" placeholder 추가

다음 JSON 형식으로만 응답하세요:
{{
  "title": "블로그 포스트 제목",
  "slug": "url-friendly-slug-in-korean-or-english",
  "body_markdown": "전체 본문 (Markdown 형식)",
  "aida_structure": {{
    "attention": "Attention 파트 요약",
    "interest": "Interest 파트 요약",
    "desire": "Desire 파트 요약",
    "action": "Action 파트 요약"
  }},
  "pas_structure": {{
    "problem": "Problem 파트 요약",
    "agitation": "Agitation 파트 요약",
    "solution": "Solution 파트 요약"
  }}
}}
"""

PROMPT_S4_TONE = """\
아래 ETF 블로그 원고를 한국어 금융 블로그 톤으로 다듬어주세요.

원고:
{draft_body}

조정 요구사항:
1. 과도한 전문용어·영어 줄임 (꼭 필요한 경우 괄호로 한국어 설명 병기)
2. 문장을 더 자연스럽고 읽기 쉽게 다듬기
3. 투자 권유 표현 제거 → 정보 제공 표현으로 교체
4. 각 H2 섹션 첫 문장은 정의형 또는 결론형으로 시작
5. FAQ Q&A 형식 명확하게 유지

수정된 body_markdown만 반환하세요 (JSON 없이 Markdown 텍스트만).
"""

PROMPT_S4_FACTCHECK = """\
아래 ETF 블로그 원고의 사실 정확성을 검토하세요.

원고:
{toned_body}

검토 항목:
1. 구체적 수치 (수익률, 보수율 등) → 명확한 출처 없으면 [확인 필요: 수치] 태그 추가
2. 특정 ETF 상품명 → 정확한 종목코드/상품명인지 확인, 불확실하면 [확인 필요: ETF명] 태그 추가
3. 법·세제 내용 → 변경 가능성 있으면 "본 내용은 YYYY년 기준이며 변경될 수 있습니다" 주석 추가
4. 잘못된 사실 → 수정 또는 [확인 필요] 태그
5. 출처 표기 주의사항:
   - [출처: KRX]는 한국거래소가 직접 발표한 통계·데이터에만 사용. ETF 상품 정보·수익률 비교 등에는 사용 금지
   - [출처: 운용사 공시], [출처: 금융투자협회] 등 실제 원출처를 정확히 기재
   - 원출처가 불명확한 수치에는 반드시 [확인 필요: 출처] 태그 추가

수정된 body_markdown만 반환하세요 (JSON 없이 Markdown 텍스트만).
"""

PROMPT_S5 = """\
아래 ETF 블로그 원고를 AI Overview(Google) 및 Naver Cue가 인용하기 좋은 구조로 최적화하세요.

원고:
{body_markdown}

최적화 기준:
1. 각 섹션 첫 문장: 정의형 또는 결론형으로 시작
2. 단문 위주 (문장당 40자 이내)
3. FAQ 섹션: Q&A 명확히 분리 (## FAQ 헤더 사용)
4. 출처 링크 [출처: XXX]: 핵심 주장 직후 배치
5. 핵심 개념에 굵은 글씨 적용
6. 목록(ul/ol) 활용하여 스캐너블하게 구성

⚠️ 중요 제약사항:
- **원문 분량을 반드시 2,000자 이상 유지**하세요. 내용을 요약·압축해서 줄이지 마세요.
- 기존 섹션, FAQ, 예시를 삭제하지 말고 형식만 최적화하세요.
- [이미지: 설명] placeholder와 [더 알아보기: ...] CTA는 그대로 유지하세요.

다음 JSON 형식으로만 응답하세요:
{{
  "optimized_markdown": "최적화된 전체 본문 (원문 분량 이상 유지)",
  "geo_score": {{
    "ai_overview": 0~100,
    "naver_cue": 0~100
  }},
  "improvements": ["개선 사항 3가지 (구체적으로)"]
}}
"""

CONTENT_FOOTER = """\


---

> 📌 **더 읽어보기**: [관련 ETF 콘텐츠 링크]
> 💬 **ETF 투자 궁금한 점 있으신가요?** [Acme ETF 투자 가이드]로 이동하기

*AI 생성 콘텐츠 · 투자 권유 아님 · 모든 투자 결정은 본인 판단과 책임 하에*
"""

PROMPT_CONTENT_IDEAS = """\
당신은 Acme Asset Management ETF 마케팅팀의 콘텐츠 전략가입니다.
아래 ETF 키워드 클러스터와 독자 JTBD 분석, 경쟁사 공백 분석을 바탕으로 카드뉴스·SNS용 콘텐츠 아이디어를 생성하세요.

클러스터명: {cluster_name}
대표 키워드: {keywords}
독자 핵심 Job: {main_job}
기능적 니즈: {functional_needs}
감성적 니즈: {emotional_needs}
독자 상황: {hire_context}
차별화 각도 (Pillar Angle): {pillar_angle}
경쟁사 공백 (Competitor Gaps): {competitor_gaps}

생성 요구사항:
- 카드뉴스 아이디어: 3개 × (주제 1개 + 카드별 제목 5~7장 + 핵심 메시지 1문장)
  * 각 카드뉴스는 AIDA(Attention→Interest→Desire→Action) 또는 PAS(Problem→Agitation→Solution) 구조를 따르되,
    첫 카드는 Attention/Problem, 마지막 카드는 Action/Solution으로 설계
  * competitor_gaps 중 1개 이상을 반드시 반영해 경쟁사 대비 차별 포인트 명시
- 블로그 제목: 5개 (검색 클릭률 최적화, 숫자/질문 포함, 50자 이내)
  * pillar_angle 차별화 관점을 제목에 녹여 경쟁사 대비 차별성 강조
- 유튜브 제목: 3개 (썸네일 클릭 유도형, 35자 이내)
- SNS 메시지: 5개 (인스타그램/스레드용, 140자 이내, 해시태그 3개 포함)
- 팀장 보고용 한 줄 요약: 이번 주 이 클러스터를 왜 다뤄야 하는지 1문장

현재 연도: {today_year}년 (수치·한도·세법 기준 연도는 반드시 {today_year}년 기준으로 표기)

브랜드 톤: Acme ETF — 전문적이지만 친근하게, 투자 권유 표현 금지

📊 참고 ETF 데이터 (운용사 중립 — 시총/거래량 기준 자동 선별):
{rag_context}

⛔ 절대 사용 금지 표현:
- "우회", "회피", "꼼수", "절세 꿀팁" (금융규제 회피 뉘앙스)
- "지금 바로 매수", "오늘 딱 N주", "지금 사세요" (매수 행위 직접 유도)
- "무조건", "확실", "보장" (수익 보장 뉘앙스)
- 과거 연도(예: 2024, 2025) + 한도/세법 조합 (구버전 정보 오인 방지)

📌 수치 사용 규칙:
- 수익률, 순자산(AUM), 총보수(TER), 세액공제액, 납입한도 등 구체적 수치를 언급할 때는
  반드시 뒤에 [확인 필요: 출처] 태그를 붙이세요. 예: "연 148만 원 세액공제 [확인 필요: 국세청]"
- ETF 상품 수치는 [확인 필요: 운용사 공시] 태그 사용
- 수치가 없는 개념·구조 설명에는 태그 불필요

다음 JSON 형식으로만 응답하세요:
{{
  "cluster_name": "{cluster_name}",
  "keywords": {keywords_json},
  "card_news_ideas": [
    {{
      "topic": "카드뉴스 주제",
      "card_titles": ["카드1 제목", "카드2 제목", ...],
      "key_message": "이 카드뉴스의 핵심 메시지 1문장"
    }}
  ],
  "blog_titles": ["제목1", "제목2", "제목3", "제목4", "제목5"],
  "youtube_titles": ["제목1", "제목2", "제목3"],
  "sns_messages": ["메시지1 #해시1 #해시2 #해시3", ...],
  "one_liner": "팀장 보고용 한 줄 요약"
}}
"""

PROMPT_CONTENT_BRIEF_SEARCH = """\
아래는 이번 주 실제 투자자들이 네이버 블로그에서 가장 많이 검색하고 작성한 ETF 키워드 클러스터입니다.
이 클러스터가 이번 주 콘텐츠 브리프의 핵심 주제 축입니다.

[이번 주 투자자 관심 클러스터]
{cluster_summary}

위 클러스터 각각에 대해 오늘 날짜 기준 실시간 시장 데이터를 조사해주세요.
클러스터 키워드와 직접 연결된 ETF 뉴스·수익률·시장 흐름을 찾아 아래 형식으로 정리하세요:

클러스터별 조사 항목:
1. 해당 클러스터와 연관된 최신 시장 트렌드 또는 뉴스 헤드라인
2. 관련 ETF의 최근 수익률·거래량·자금 흐름 수치 (가능한 경우)
3. 이 클러스터가 이번 주 콘텐츠로 적합한 이유 (시장 타이밍)

클러스터 외에 이번 주 ETF 시장에서 놓치면 안 되는 추가 트렌드가 있으면 1~2개 보충해도 됩니다.
결과를 구체적인 텍스트로 제공해주세요.
"""

PROMPT_HALLUCINATION_CHECK = """\
당신은 금융 콘텐츠의 사실 정확성을 검증하는 전문가입니다.
아래 ETF 마케팅 콘텐츠에서 사실 확인이 필요한 주장을 추출하고 위험도를 평가하세요.

[콘텐츠]
{content_text}

검증 대상:
1. 수치 (수익률, AUM, TER, 세액공제액, 납입한도 등)
2. 상품명 (ETF명, 종목코드)
3. 법·세제 주장 (세법, 투자 규정)

각 주장에 대해 다음을 확인하세요:
- [확인 필요: 출처] 태그가 붙어있는지 여부 (source_tag_present)
- 태그 없이 단정적으로 기술된 수치/상품명/법제 주장은 risk를 높게 설정
- 개념·구조 설명(수치 없음)은 검증 대상 아님

위험도 기준:
- 0~30: 출처 태그 있거나 검증 불필요
- 31~69: 출처 태그 없지만 일반적으로 알려진 사실
- 70~100: 출처 태그 없고 구체적 수치/상품명/법제 단정 기술

반드시 다음 JSON 스키마를 준수해서 JSON만 반환하세요:
{{
  "overall_risk": 0~100의 정수 (claims의 risk 평균),
  "claims": [
    {{
      "text": "원문에서 발췌한 주장 (50자 이내)",
      "claim_type": "number" | "product" | "legal",
      "risk": 0~100의 정수,
      "reason": "위험도 판단 근거 1문장",
      "source_tag_present": true | false
    }}
  ],
  "summary": "전반적 할루시네이션 위험 요약 1~2문장"
}}

검증 대상 주장이 없으면 claims를 빈 배열로 반환하세요.
"""

PROMPT_AIDA_PAS_RUBRIC = """\
당신은 마케팅 프레임워크 전문가입니다.
아래 ETF 마케팅 콘텐츠 아이디어들이 AIDA 또는 PAS 구조를 얼마나 준수하는지 채점하세요.

[채점 대상]
{content_items}

채점 기준:
AIDA 체크리스트 (각 1점, 총 4점):
- attention: 첫 카드/제목이 주목을 끄는 질문·숫자·문제제기로 시작하는가
- interest: 구체적 정보·수치·사례로 흥미를 유지하는가
- desire: 독자가 갖고 싶거나 하고 싶게 만드는 욕구 유발 요소가 있는가
- action: 다음 행동(검색, 클릭, 투자 고려)을 유도하는 마무리가 있는가

PAS 체크리스트 (각 1점, 총 3점):
- problem: 독자의 투자 고민/문제를 명확히 제시하는가
- agitation: 해결 안 했을 때의 불안/손실을 심화시키는가
- solution: 구체적 해결책(ETF 활용법 등)을 제시하는가

각 아이디어에 대해 AIDA와 PAS 중 더 적합한 프레임을 선택해 채점하세요.
normalized_score = (체크리스트 합산 / 최대 점수) × 10으로 정규화 (소수점 1자리)

반드시 다음 JSON 스키마를 준수해서 JSON만 반환하세요:
{{
  "scores": [
    {{
      "idea_id": "카드뉴스1" | "블로그1~5" | "SNS1~5" 등 식별자,
      "framework": "AIDA" | "PAS",
      "checklist": {{"attention": 0|1, "interest": 0|1, "desire": 0|1, "action": 0|1}} 또는
                   {{"problem": 0|1, "agitation": 0|1, "solution": 0|1}},
      "normalized_score": 0.0~10.0,
      "comment": "채점 근거 1문장"
    }}
  ],
  "avg_score": 모든 scores의 normalized_score 평균 (소수점 1자리)
}}
"""

QUALITY_THRESHOLDS: dict[str, int] = {"green": 8, "yellow": 5}

PROMPT_CONTENT_BRIEF_STRUCTURE = """\
아래 ETF 시장 트렌드 데이터와 독자 JTBD 분석을 결합해 이번 주 마케팅팀 콘텐츠 브리프를 작성하세요.

현재 날짜: {today} (모든 수치·한도·세법 기준은 반드시 {today_year}년 기준으로 표기. 과거 연도 수치 사용 금지)
ETF 클러스터 요약:
{cluster_summary}

경쟁사 공백 분석 (S3 Competitor Gaps):
{competitor_gaps_summary}

JTBD 분석 요약:
{jtbd_summary}

시장 트렌드 조사 결과:
{market_trends}

작성 요구사항:
- 주차 레이블: "{week_label}"
- 트렌드 시그널 5개: 각각 주제·방향성·근거·JTBD 질문 포함
  ⚠️ 시그널 작성 우선순위:
  1순위: 위 ETF 클러스터 목록의 각 클러스터를 시그널 주제로 직접 사용하세요.
          클러스터 수만큼 시그널을 먼저 채우고, 남은 자리는 시장 트렌드 조사 결과로 보충합니다.
  2순위: 클러스터로 채우고 남은 시그널만 시장 트렌드 조사 결과에서 선택합니다.
  (JTBD 질문: 독자가 실제로 묻는 질문 형식, 예: "금리 인하 시 내 채권 ETF는 어떻게 될까?")
- 이번 주 콘텐츠 방향: 시그널을 종합한 1단락 가이드
  * ML 클러스터 기반 독자 관심사와 실시간 시장 트렌드가 교차하는 지점을 핵심 방향으로 제시
  * competitor_gaps를 반영해 경쟁사가 다루지 않는 공백을 우리가 채울 방향 명시
  * 이번 주 콘텐츠에 적용할 AIDA 또는 PAS 프레임을 1문장으로 명시
- 추천 콘텐츠 형식: 카드뉴스/블로그/유튜브 쇼츠 중 우선순위 3개
- 긴급성 이유: 왜 이번 주에 이 주제인지 1문장

📊 참고 ETF 데이터 (운용사 중립 — 시총/거래량 기준 자동 선별):
{rag_context}

📌 수치 신뢰성 규칙:
- evidence 필드에 수익률·AUM·납입한도 등 수치를 쓸 때는 반드시 "(출처: XXX)" 또는
  "[확인 필요: 출처]" 형식으로 출처를 명시하세요.
- 출처가 불명확한 수치는 [확인 필요: 출처] 태그로 표시하세요.
- 모든 연도 기준은 {today_year}년이어야 합니다.

다음 JSON 형식으로만 응답하세요:
{{
  "week_label": "{week_label}",
  "top_signals": [
    {{
      "topic": "트렌드 주제",
      "trend_direction": "급상승" | "상승" | "유지" | "하락",
      "evidence": "근거 1문장 (출처 포함)",
      "jtbd_question": "독자가 실제로 묻는 질문"
    }}
  ],
  "content_direction": "이번 주 콘텐츠 방향 1단락 (competitor_gaps 활용 + AIDA/PAS 프레임 포함)",
  "recommended_formats": ["카드뉴스", "블로그", "유튜브 쇼츠"],
  "urgency_reason": "왜 이번 주에 이 주제인지 1문장"
}}
"""
