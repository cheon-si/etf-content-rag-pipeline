"""
ETF 블로그 자동화 파이프라인 보고서 생성기
Brand orange color theme
"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import copy

# ── Brand color ────────────────────────────────────────────────
ORANGE      = RGBColor(0xF3, 0x6B, 0x21)   # Brand main orange
ORANGE_LIGHT= RGBColor(0xFF, 0xE0, 0xC8)   # 연한 오렌지 (표 헤더 배경)
ORANGE_BG   = RGBColor(0xFF, 0xF3, 0xEB)   # 아주 연한 오렌지 (섹션 배경)
DARK_NAVY   = RGBColor(0x1A, 0x1A, 0x2E)   # 네이비 (제목)
MID_GRAY    = RGBColor(0x55, 0x55, 0x55)   # 본문 텍스트
LIGHT_GRAY  = RGBColor(0xF5, 0xF5, 0xF5)   # 표 행 배경
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)
GREEN       = RGBColor(0x27, 0xAE, 0x60)
RED_COL     = RGBColor(0xE7, 0x4C, 0x3C)


# ── 헬퍼 함수 ────────────────────────────────────────────────────
def set_cell_bg(cell, color: RGBColor):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    hex_color = f"{color[0]:02X}{color[1]:02X}{color[2]:02X}"
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)

def set_cell_border(cell, top=None, bottom=None, left=None, right=None):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement('w:tcBorders')
    for side, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        if val:
            border = OxmlElement(f'w:{side}')
            border.set(qn('w:val'), 'single')
            border.set(qn('w:sz'), '12')
            border.set(qn('w:space'), '0')
            border.set(qn('w:color'), val)
            tcBorders.append(border)
    tcPr.append(tcBorders)

def add_run_colored(para, text, color=None, bold=False, size=None, italic=False):
    run = para.add_run(text)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = color
    if size:
        run.font.size = Pt(size)
    return run

def set_para_spacing(para, before=0, after=0, line=None):
    pf = para.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after  = Pt(after)
    if line:
        pf.line_spacing = Pt(line)

def add_orange_divider(doc):
    """오렌지 구분선 단락 추가"""
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), 'F36B21')
    pBdr.append(bottom)
    pPr.append(pBdr)
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after  = Pt(6)
    return p

def add_page_break(doc):
    doc.add_page_break()

def heading1(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(18)
    p.paragraph_format.space_after  = Pt(6)
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(16)
    run.font.color.rgb = DARK_NAVY
    add_orange_divider(doc)
    return p

def heading2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after  = Pt(4)
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = ORANGE
    return p

def heading3(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after  = Pt(3)
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = DARK_NAVY
    return p

def body(doc, text, indent=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after  = Pt(4)
    if indent:
        p.paragraph_format.left_indent = Cm(0.6)
    run = p.add_run(text)
    run.font.size = Pt(10)
    run.font.color.rgb = MID_GRAY
    return p

def bullet(doc, text, level=0):
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after  = Pt(2)
    p.paragraph_format.left_indent  = Cm(0.5 + level * 0.5)
    run = p.add_run(text)
    run.font.size = Pt(10)
    run.font.color.rgb = MID_GRAY
    return p

def callout_box(doc, title, content, color=None):
    """강조 박스 (표 1×1로 구현)"""
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    cell = t.cell(0, 0)
    bg = color or ORANGE_BG
    set_cell_bg(cell, bg)
    set_cell_border(cell, top='F36B21', bottom='F36B21', left='F36B21', right='F36B21')
    cell.width = Cm(15)
    p_title = cell.add_paragraph()
    p_title.paragraph_format.space_before = Pt(4)
    p_title.paragraph_format.space_after  = Pt(2)
    p_title.paragraph_format.left_indent  = Cm(0.3)
    r = p_title.add_run(title)
    r.bold = True
    r.font.size = Pt(10)
    r.font.color.rgb = ORANGE
    p_body = cell.add_paragraph()
    p_body.paragraph_format.space_before = Pt(0)
    p_body.paragraph_format.space_after  = Pt(4)
    p_body.paragraph_format.left_indent  = Cm(0.3)
    rb = p_body.add_run(content)
    rb.font.size = Pt(9.5)
    rb.font.color.rgb = MID_GRAY
    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return t


def build_comparison_table(doc, headers, rows, col_widths=None):
    """비교 표 생성"""
    n_cols = len(headers)
    t = doc.add_table(rows=1+len(rows), cols=n_cols)
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    t.style = 'Table Grid'

    # 헤더
    for i, h in enumerate(headers):
        cell = t.cell(0, i)
        set_cell_bg(cell, ORANGE)
        set_cell_border(cell, top='F36B21', bottom='F36B21', left='FFFFFF', right='FFFFFF')
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after  = Pt(3)
        run = p.add_run(h)
        run.bold = True
        run.font.size = Pt(9.5)
        run.font.color.rgb = WHITE

    # 데이터 행
    for ri, row in enumerate(rows):
        bg = LIGHT_GRAY if ri % 2 == 0 else WHITE
        for ci, val in enumerate(row):
            cell = t.cell(ri+1, ci)
            set_cell_bg(cell, bg)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after  = Pt(2)
            p.paragraph_format.left_indent  = Cm(0.15)
            if isinstance(val, tuple):
                # (text, bold, color)
                text, bold, color = val
                run = p.add_run(text)
                run.bold = bold
                run.font.size = Pt(9.5)
                run.font.color.rgb = color
            else:
                run = p.add_run(str(val))
                run.font.size = Pt(9.5)
                run.font.color.rgb = MID_GRAY

    # 열 너비
    if col_widths:
        for ci, w in enumerate(col_widths):
            for ri in range(len(rows)+1):
                t.cell(ri, ci).width = Cm(w)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return t


# ════════════════════════════════════════════════════════════════
#  문서 생성
# ════════════════════════════════════════════════════════════════
doc = Document()

# ── 여백 설정 ─────────────────────────────────────────────────
for section in doc.sections:
    section.top_margin    = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin   = Cm(3.0)
    section.right_margin  = Cm(2.5)

# ── 기본 폰트 ─────────────────────────────────────────────────
style = doc.styles['Normal']
style.font.name = '맑은 고딕'
style.font.size = Pt(10)


# ════════════════════════════════════════════════════════════════
#  표지 (Cover Page)
# ════════════════════════════════════════════════════════════════

# 상단 오렌지 배너 (표 활용)
banner = doc.add_table(rows=1, cols=1)
banner.alignment = WD_TABLE_ALIGNMENT.LEFT
bc = banner.cell(0, 0)
set_cell_bg(bc, ORANGE)
bc.width = Cm(15)
bp = bc.paragraphs[0]
bp.alignment = WD_ALIGN_PARAGRAPH.LEFT
bp.paragraph_format.space_before = Pt(10)
bp.paragraph_format.space_after  = Pt(10)
bp.paragraph_format.left_indent  = Cm(0.5)
r = bp.add_run('ACME  |  Content Marketing Team')
r.bold = True
r.font.size = Pt(11)
r.font.color.rgb = WHITE

doc.add_paragraph()

# 타이틀
p_title = doc.add_paragraph()
p_title.alignment = WD_ALIGN_PARAGRAPH.LEFT
p_title.paragraph_format.space_before = Pt(30)
p_title.paragraph_format.space_after  = Pt(6)
r1 = p_title.add_run('ETF 블로그 콘텐츠\n자동화 파이프라인')
r1.bold = True
r1.font.size = Pt(30)
r1.font.color.rgb = DARK_NAVY

p_sub = doc.add_paragraph()
p_sub.paragraph_format.space_before = Pt(4)
p_sub.paragraph_format.space_after  = Pt(4)
rs = p_sub.add_run('LLM 기반 AI 자동 원고 생성 시스템 도입 보고서')
rs.font.size = Pt(14)
rs.font.color.rgb = ORANGE
rs.bold = True

add_orange_divider(doc)

# 메타 정보 표
meta = doc.add_table(rows=4, cols=2)
meta.alignment = WD_TABLE_ALIGNMENT.LEFT
meta_data = [
    ('보고일', '2026년 4월 22일'),
    ('작성자', '시원 (Content Marketing Team)'),
    ('검토 대상', '클러스터 1: AI·반도체·성장 (네이버 블로그 123개 포스트)'),
    ('사용 모델', 'Claude Sonnet 4.6 / Opus 4.7 + Gemini 2.5 Flash'),
]
for i, (k, v) in enumerate(meta_data):
    ck = meta.cell(i, 0)
    cv = meta.cell(i, 1)
    set_cell_bg(ck, ORANGE_LIGHT)
    ck.width = Cm(3.5)
    cv.width = Cm(11.5)
    pk = ck.paragraphs[0]
    pk.paragraph_format.space_before = Pt(3)
    pk.paragraph_format.space_after  = Pt(3)
    pk.paragraph_format.left_indent  = Cm(0.2)
    rk = pk.add_run(k)
    rk.bold = True
    rk.font.size = Pt(9.5)
    rk.font.color.rgb = DARK_NAVY
    pv = cv.paragraphs[0]
    pv.paragraph_format.space_before = Pt(3)
    pv.paragraph_format.space_after  = Pt(3)
    pv.paragraph_format.left_indent  = Cm(0.2)
    rv = pv.add_run(v)
    rv.font.size = Pt(9.5)
    rv.font.color.rgb = MID_GRAY

doc.add_paragraph()

# 요약 박스
callout_box(doc,
    '📌 핵심 요약',
    '네이버 블로그 ETF 키워드 클러스터링 데이터를 입력으로 받아 '
    '5단계 LLM 파이프라인(Intent → JTBD → 콘텐츠 설계 → 본문 초안 → GEO 최적화)을 통해 '
    '블로그 원고를 자동 생성합니다. Gemini 2.5 Flash의 실시간 웹 검색(Search grounding)을 '
    '적용한 결과 원고 품질과 GEO 점수가 개선되었으며, 1편당 생성 비용은 약 $0.93(₩1,300)입니다.'
)

add_page_break(doc)


# ════════════════════════════════════════════════════════════════
#  1장. 최종 결과물
# ════════════════════════════════════════════════════════════════
heading1(doc, '1장. 최종 생성 원고')

p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(6)
r = p.add_run('아래는 파이프라인이 자동 생성한 최종 블로그 원고입니다. '
              '편집 없이 그대로 네이버 블로그에 게시할 수 있는 상태이며, '
              '투자 권유 문구·팩트 미확인 항목은 [확인 필요] 태그로 자동 표시됩니다.')
r.font.size = Pt(10)
r.font.color.rgb = MID_GRAY

# 원고 박스
article_lines = [
    ('# 2025 AI·반도체 ETF 완전정복: 밸류체인부터 종목·ETF 선택까지 한 번에', 'h1'),
    ('', 'space'),
    ('## 왜 지금 AI·반도체 ETF를 살펴볼까', 'h2'),
    ('AI·반도체 ETF는 미래 투자 핵심입니다.', 'body'),
    ('글로벌 반도체 시장은 2030년 1조 달러를 넘어설 전망입니다 [출처: SIA].', 'body'),
    ('엔비디아 시가총액은 3조 달러를 돌파했습니다 [출처: Bloomberg].', 'body'),
    ('개인 투자자 고민이 적지 않습니다. 수혜 기업·진입 시점 판단이 어렵고, 개별 종목의 큰 변동성도 부담입니다.', 'body'),
    ('이 글은 AI·반도체 산업을 기술→기업→ETF→거시환경→리스크 5단계로 정리합니다.', 'body'),
    ('', 'space'),
    ('## 1단계: AI·반도체 밸류체인 이해하기', 'h2'),
    ('AI·반도체 밸류체인은 핵심입니다. 반도체 산업은 크게 네 단계로 나뉩니다.', 'body'),
    ('• 팹리스(설계 전문): 엔비디아, AMD, 브로드컴', 'bullet'),
    ('• 파운드리(위탁 생산): TSMC, 삼성전자', 'bullet'),
    ('• 반도체 장비: ASML, 어플라이드 머티리얼즈(AMAT), 램리서치, 도쿄일렉트론', 'bullet'),
    ('• 메모리·HBM: SK하이닉스, 삼성전자, 마이크론', 'bullet'),
    ('현재 공급 병목 중심에는 GPU와 HBM 메모리가 있습니다. AI 데이터센터 관련 빅테크 CAPEX는 빠르게 확대됩니다.', 'body'),
    ('', 'space'),
    ('## 2단계: 핵심 기업과 실적 체크포인트', 'h2'),
    ('핵심 기업 실적은 필수 확인 사항입니다. 엔비디아 실적은 업계 전반의 방향성을 가늠하는 지표입니다.', 'body'),
    ('눈여겨볼 지표: ① 데이터센터 부문 매출 성장률  ② HBM 공급 계약 규모  ③ 파운드리 가동률과 단가 변화', 'body'),
    ('', 'space'),
    ('## 3단계: AI·반도체 ETF 선택 프레임', 'h2'),
    ('AI·반도체 ETF는 분산 투자의 핵심입니다. 테마 안에서도 유형이 다릅니다.', 'body'),
    ('• 미국 반도체 추종형: 필라델피아 반도체 지수(SOX) 기반', 'bullet'),
    ('• 국내 AI·반도체형: 삼성전자·SK하이닉스 중심', 'bullet'),
    ('• 테마 집중형: HBM, 온디바이스 AI 등 세부 테마', 'bullet'),
    ('ETF 선택 시 확인할 5가지: 추종지수·편입종목 / 총보수(TER) / 환헤지 여부 / AUM 규모 / 분배금 정책 [출처: KRX]', 'body'),
    ('', 'space'),
    ('## 4단계: 거시환경과 리스크 점검', 'h2'),
    ('거시환경과 리스크를 점검하세요. 장기 투자 시 위험 요인 인지가 필수입니다.', 'body'),
    ('• 지정학 리스크: 미·중 반도체 수출 규제 강화', 'bullet'),
    ('• 사이클 리스크: 메모리 업황의 주기적 변동', 'bullet'),
    ('• 밸류에이션 리스크: AI 기대감에 따른 고평가 논란', 'bullet'),
    ('• 환율 리스크: 원/달러 환율 변동', 'bullet'),
    ('', 'space'),
    ('## FAQ', 'h2'),
    ('Q. AI ETF와 반도체 ETF는 어떻게 다른가요?', 'q'),
    ('A. AI ETF는 소프트웨어·플랫폼 기업까지 폭넓게 포함합니다. 반도체 ETF는 칩 설계·제조·장비 기업에 집중됩니다.', 'a'),
    ('Q. 처음 시작한다면 어떤 ETF를 살펴보면 좋을까요?', 'q'),
    ('A. 순자산(AUM)이 크고 총보수가 낮은 대표 지수 추종형이 변동성 관리 측면에서 참고하기 좋다고 평가됩니다.', 'a'),
    ('Q. 환헤지형과 환노출형 중 어떤 쪽을 골라야 하나요?', 'q'),
    ('A. 달러 강세 구간에서는 환노출형이 유리합니다. 방향이 불확실하면 둘을 나눠 담는 방법도 있습니다.', 'a'),
    ('Q. 개별 종목과 ETF 중 무엇이 더 나은가요?', 'q'),
    ('A. ETF는 분산 효과로 리스크를 낮춥니다. 개별 종목은 상방 수익률이 크지만 변동성도 커집니다.', 'a'),
    ('', 'space'),
    ('※ 본 콘텐츠는 정보 제공 목적이며, 특정 상품에 대한 투자 권유가 아닙니다.', 'notice'),
]

art_table = doc.add_table(rows=1, cols=1)
art_table.alignment = WD_TABLE_ALIGNMENT.LEFT
art_cell = art_table.cell(0, 0)
set_cell_bg(art_cell, RGBColor(0xFD, 0xFD, 0xFD))
set_cell_border(art_cell, top='E0E0E0', bottom='E0E0E0', left='F36B21', right='E0E0E0')

for text, style_name in article_lines:
    if style_name == 'space':
        ep = art_cell.add_paragraph()
        ep.paragraph_format.space_after = Pt(2)
        continue
    p = art_cell.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.4)
    if style_name == 'h1':
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after  = Pt(4)
        r = p.add_run(text.replace('# ', ''))
        r.bold = True; r.font.size = Pt(13); r.font.color.rgb = DARK_NAVY
    elif style_name == 'h2':
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after  = Pt(3)
        r = p.add_run(text.replace('## ', ''))
        r.bold = True; r.font.size = Pt(11); r.font.color.rgb = ORANGE
    elif style_name == 'bullet':
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after  = Pt(1)
        p.paragraph_format.left_indent  = Cm(0.8)
        r = p.add_run(text)
        r.font.size = Pt(9.5); r.font.color.rgb = MID_GRAY
    elif style_name == 'q':
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after  = Pt(1)
        r = p.add_run(text)
        r.bold = True; r.font.size = Pt(9.5); r.font.color.rgb = DARK_NAVY
    elif style_name == 'a':
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after  = Pt(3)
        p.paragraph_format.left_indent  = Cm(0.8)
        r = p.add_run(text)
        r.font.size = Pt(9.5); r.font.color.rgb = MID_GRAY
    elif style_name == 'notice':
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after  = Pt(4)
        r = p.add_run(text)
        r.italic = True; r.font.size = Pt(8.5); r.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
    else:
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after  = Pt(2)
        r = p.add_run(text)
        r.font.size = Pt(9.5); r.font.color.rgb = MID_GRAY

doc.add_paragraph()
add_page_break(doc)


# ════════════════════════════════════════════════════════════════
#  2장. 시스템 개요 및 비용
# ════════════════════════════════════════════════════════════════
heading1(doc, '2장. 시스템 개요 및 비용')

heading2(doc, '2-1. 파이프라인 구조')
body(doc, '네이버 블로그 ETF 키워드 트렌드 분석 시스템의 K-Means 클러스터링 결과를 입력으로 받아 '
         '5단계 LLM 파이프라인이 자동으로 블로그 원고를 생성합니다.')

# 파이프라인 흐름 표
build_comparison_table(doc,
    headers=['단계', '역할', '사용 모델', '핵심 프레임워크'],
    rows=[
        ('S1', 'Search Intent 분류', 'Claude Sonnet 4.6', 'Informational / Commercial / Transactional'),
        ('S2', 'JTBD 분석', 'Claude Opus 4.7', 'Jobs To Be Done (Clayton Christensen)'),
        ('S3', '콘텐츠 구조 설계', 'Gemini 2.5 Flash\n+ Claude Opus 4.7', 'Search Grounding → Pillar-Sub 설계'),
        ('S4', '본문 3-이터레이션', 'Claude Opus 4.7', 'AIDA + PAS 프레임워크'),
        ('S5', 'GEO 최적화', 'Gemini 2.5 Flash', 'AI Overview / Naver Cue 인용 구조화'),
    ],
    col_widths=[1.2, 3.0, 4.2, 6.6]
)

heading2(doc, '2-2. 비용 비교 (Gemini 전후)')
body(doc, 'Gemini 2.5 Flash 도입 후 S3·S5 비용이 각각 Opus 대비 약 1/250 수준으로 절감되었습니다.')

build_comparison_table(doc,
    headers=['단계', '모델', '입력 토큰', '출력 토큰', '비용(USD)'],
    rows=[
        ('S1', 'Sonnet 4.6', '614', '285', ('$0.0061', False, MID_GRAY)),
        ('S2', 'Opus 4.7', '1,058', '747', ('$0.0719', False, MID_GRAY)),
        ('S3 (Gemini)', 'Gemini 2.5 Flash', '195', '1,066', ('$0.0003 ★', True, GREEN)),
        ('S3 (Opus)', 'Opus 4.7', '2,992', '1,351', ('$0.1462', False, MID_GRAY)),
        ('S4-초고', 'Opus 4.7', '1,564', '2,528', ('$0.2131', False, MID_GRAY)),
        ('S4-톤교정', 'Opus 4.7', '2,088', '2,646', ('$0.2298', False, MID_GRAY)),
        ('S4-팩트체크', 'Opus 4.7', '2,935', '2,879', ('$0.2600', False, MID_GRAY)),
        ('S5 (Gemini)', 'Gemini 2.5 Flash', '2,208', '1,950', ('$0.0008 ★', True, GREEN)),
        ('합계', '—', '—', '—', ('$0.9281', True, ORANGE)),
    ],
    col_widths=[2.0, 4.0, 2.5, 2.5, 4.0]
)

callout_box(doc,
    '💡 비용 포인트',
    'Gemini 2.5 Flash의 S3 시장조사 비용은 $0.0003 (약 0.4원), S5 GEO 최적화는 $0.0008 (약 1.1원)으로 '
    '사실상 무료 수준입니다. 반면 Gemini 없이 Opus로만 처리할 경우 같은 두 단계에서 약 $0.43이 소요됩니다. '
    '월 100편 생성 기준 약 $43 절감 효과입니다.'
)

add_page_break(doc)


# ════════════════════════════════════════════════════════════════
#  3장. 단계별 처리 과정 및 전후 비교
# ════════════════════════════════════════════════════════════════
heading1(doc, '3장. 단계별 처리 과정 및 전후 비교')

body(doc, '동일한 클러스터(ai/반도체/성장, 123 포스트)를 대상으로 Gemini 미적용(1차)과 Gemini 적용(2차)을 '
         '비교합니다. S1·S2는 두 버전 모두 동일 모델(Sonnet/Opus)을 사용하며, '
         'S3·S5에서 Gemini의 실시간 웹 검색이 품질 차이를 만들어냅니다.')

# ── S1 ──────────────────────────────────────────────────────────
heading2(doc, 'S1 | Search Intent 분류 — Claude Sonnet 4.6')

callout_box(doc,
    '입력',
    '클러스터명: ai/반도체/성장  |  대표 키워드(10개): AI, 반도체, 성장, 미국, 실적, 기술, 산업, 주가, 종목, 투자'
)

body(doc, '키워드 검색자의 목적을 Informational / Commercial / Transactional 3가지로 분류합니다. '
         '이 분류에 따라 이후 단계에서 글의 톤(정보 제공 vs 구매 유도)이 결정됩니다.')

build_comparison_table(doc,
    headers=['항목', '1차 (Gemini 없음)', '2차 (Gemini 적용)'],
    rows=[
        ('분류 결과', 'Informational', 'Informational'),
        ('신뢰도', '78%', '78%'),
        ('경계 키워드', "'종목', '미국' → Commercial 경계", "'종목', '주가' → Commercial 일부 내포"),
        ('이후 영향', '투자 권유 표현 억제, 정보 제공 중심 구조 지시', '동일'),
    ],
    col_widths=[3.0, 5.5, 5.5]
)

body(doc, '→ 두 버전 모두 동일한 결론. 키워드 구성이 같기 때문에 Sonnet은 같은 판단을 내립니다.', indent=True)

# ── S2 ──────────────────────────────────────────────────────────
heading2(doc, 'S2 | JTBD 분석 — Claude Opus 4.7')

callout_box(doc,
    '입력',
    '클러스터 정보 + S1 결과(Informational 78%)  →  Clayton Christensen의 Jobs To Be Done 프레임워크 적용'
)

body(doc, '"이 콘텐츠를 왜 읽는가?"를 기능적·감정적·사회적 필요로 분해합니다. '
         '이 분석이 S4 서문 감성 문장과 FAQ 구성의 근거가 됩니다.')

build_comparison_table(doc,
    headers=['항목', '1차', '2차'],
    rows=[
        ('핵심 직무', 'AI·반도체 구조 이해로\n투자 판단 근거 마련', 'AI·반도체 흐름을 빠르게 이해해\n장기 투자 기회 선점'),
        ('고용 맥락\n(페르소나)', '"AI 열풍 뉴스를 접한\n투자자" — 추상적', '"30~40대 직장인, 퇴근길·주말,\n엔비디아 급등 뉴스" — 구체적'),
        ('감정적 필요', 'FOMO 해소, 불안 완화,\n투자 자신감', 'FOMO 해소, 지적 자신감 획득,\n막연한 불안 완화, 시대 흐름 안도감'),
        ('이후 영향', 'S4 서문: 일반적 투자자 묘사', 'S4 서문: 직장인 퇴근길 맥락 반영'),
    ],
    col_widths=[3.0, 5.5, 5.5]
)

add_page_break(doc)

# ── S3 ──────────────────────────────────────────────────────────
heading2(doc, 'S3 | 콘텐츠 구조 설계 — Gemini Search Grounding → Claude Opus 4.7')

callout_box(doc,
    '⭐ 핵심 분기점: Gemini 유무에 따라 결과물이 가장 크게 달라지는 단계',
    '1차: Gemini 실패(429 에러) → Opus 단독으로 구조 설계 (시장 조사 없음)\n'
    '2차: Gemini가 웹을 실시간 검색 → "한국어 콘텐츠 공백" 발견 → Opus가 이 데이터로 구조 설계'
)

heading3(doc, 'Gemini Search Grounding 시장조사 결과 (2차만)')
body(doc, 'Gemini 2.5 Flash가 21초, $0.0003 비용으로 다음을 조사했습니다:')
bullet(doc, '상위 노출 콘텐츠 공통 패턴: 엔비디아·TSMC 개별 주가 분석 중심, ETF 단순 소개 위주')
bullet(doc, '콘텐츠 공백 발견: GPU·NPU·ASIC 기술 차이 설명 없음 / 기업 간 정량 비교 없음 / 리스크 설명 부재')
bullet(doc, '경쟁 각도: 단기 수익률 위주, 초보자 기술 설명 없음')

heading3(doc, 'Pillar 구조 비교')

build_comparison_table(doc,
    headers=['항목', '1차 (시장조사 없음)', '2차 (Gemini 조사 반영)'],
    rows=[
        ('Pillar 제목', 'AI·반도체 ETF 완벽 가이드:\n미래 성장 산업에 올라타는 투자자의 지도', '2025 AI·반도체 ETF 완전정복:\n밸류체인부터 종목·ETF 선택까지 한 번에'),
        ('서브토픽 ①', 'AI·반도체 밸류체인 완전 해부', ('AI 반도체 기술 구조: GPU·NPU·ASIC·HBM 구분\n← Gemini가 "초보자 기술 설명 부재" 발견', True, GREEN)),
        ('서브토픽 ②', '미국 빅테크 vs 반도체 주도주\n실적·주가 비교', '엔비디아·삼성·SK하이닉스·AMD\n기업 심층 비교 (정량 비교 추가)'),
        ('서브토픽 ③', 'AI·반도체 테마 ETF\n구성 종목 비교 (SOXX·SMH·AIQ)', 'ETF 베스트 7 비교\n(국내 KODEX 포함으로 확장)'),
        ('서브토픽 ④', '금리·환율이 AI·반도체\n주가에 미치는 영향', '금리·환율이 수익률에 미치는 영향:\n거시경제로 타이밍 잡기 (더 실전적)'),
        ('서브토픽 ⑤', '개별 종목 vs 테마 ETF 비교', ('AI 버블론·지정학 리스크 총정리\n← Gemini가 "리스크 설명 부재" 발견', True, GREEN)),
    ],
    col_widths=[3.0, 5.5, 5.5]
)

body(doc, '→ ①번(기술 구조)과 ⑤번(리스크) 서브토픽이 완전히 교체되었습니다. '
         'Gemini가 실제 웹에서 "한국어 콘텐츠에 이 내용이 없다"는 걸 확인한 결과입니다.', indent=True)

# ── S4 ──────────────────────────────────────────────────────────
add_page_break(doc)
heading2(doc, 'S4 | 본문 3-이터레이션 — Claude Opus 4.7')

callout_box(doc,
    '입력',
    'S3 결과(Pillar 구조 + 경쟁 갭) + S2 결과(JTBD)  →  3회 연속 대화로 원고를 단계적으로 완성'
)

body(doc, 'S3 구조의 차이가 S4에서 증폭됩니다. Gemini 조사가 반영된 구조를 받은 2차 Opus는 '
         '더 구체적인 기업 목록과 출처가 있는 원고를 작성했습니다.')

heading3(doc, '이터레이션 1: 초고 작성 (AIDA 프레임워크)')

build_comparison_table(doc,
    headers=['AIDA 요소', '1차 Opus 초고', '2차 Opus 초고'],
    rows=[
        ('Attention\n(주목)', '엔비디아 시총 3조 달러\n[확인 필요: 수치 및 시점]',
         '반도체 시장 2030년 1조 달러 [출처: SIA]\n엔비디아 3조 달러 [출처: Bloomberg]'),
        ('Interest\n(흥미)', '밸류체인 4단계 구조화', '밸류체인 + GPU·HBM 병목 지점 추가 설명'),
        ('Desire\n(욕구)', 'SOXX/SMH/AIQ ETF 목록', '국내 ETF 유형 3가지 + 5가지 체크리스트'),
        ('Action\n(행동)', '분할 매수·포트폴리오 점검', '실적 캘린더 작성, 리스크 체크리스트 점검\n(더 구체적 행동 지시)'),
    ],
    col_widths=[2.5, 5.5, 6.0]
)

heading3(doc, '기업 목록 비교 — 가장 체감되는 차이')

build_comparison_table(doc,
    headers=['카테고리', '1차', '2차'],
    rows=[
        ('팹리스', '엔비디아, AMD, 퀄컴', ('엔비디아, AMD, 브로드컴 (브로드컴 추가)', False, MID_GRAY)),
        ('반도체 장비', 'ASML, 어플라이드 머티리얼즈',
         ('ASML, 어플라이드 머티리얼즈,\n램리서치, 도쿄일렉트론 (2개 추가)', True, GREEN)),
        ('HBM 설명', '단순 언급 없음',
         ('HBM = 메모리 반도체 카테고리로 명시\n(SK하이닉스 주도 구조 설명)', True, GREEN)),
        ('[확인 필요] 태그', '5개', '2개 (출처 명시로 대체)'),
        ('[출처] 태그', '0개', ('3개: [SIA], [Bloomberg], [KRX]', True, GREEN)),
    ],
    col_widths=[3.0, 5.0, 6.0]
)

heading3(doc, '이터레이션 2: 어조 교정 / 이터레이션 3: 팩트 체크')
body(doc, '이터레이션 2에서 투자 권유 표현을 정보 제공 표현으로 교체하고, '
         '2차는 Gemini가 찾아온 출처를 삽입해 [확인 필요] 태그 수를 절반으로 줄였습니다.')
body(doc, '이터레이션 3에서 검증이 불가한 수치에 [확인 필요] 태그를 추가로 삽입해 '
         '컴플라이언스 리스크를 줄였습니다.')

# ── S5 ──────────────────────────────────────────────────────────
add_page_break(doc)
heading2(doc, 'S5 | GEO 최적화 — Gemini 2.5 Flash')

callout_box(doc,
    '⭐ 두 번째 핵심 분기점: GEO 점수 86/88 → 90/90 상승',
    '1차: Gemini 실패 → Opus 폴백 (GEO 일반 원칙 적용)\n'
    '2차: Gemini가 현재 AI Overview·Naver Cue 인용 패턴을 실시간 검색 → 최신 기준으로 최적화'
)

body(doc, 'GEO(Generative Engine Optimization)는 구글 AI Overview·네이버 Cue가 이 글을 '
         '인용하기 좋은 구조로 만드는 작업입니다. AI 검색엔진은 첫 문장이 정의형이고 '
         '굵은 글씨로 강조된 콘텐츠를 인용 후보로 우선 선택합니다.')

build_comparison_table(doc,
    headers=['항목', '1차 (Opus 폴백)', '2차 (Gemini 직접)'],
    rows=[
        ('AI Overview 점수', '86점', ('90점 (+4)', True, GREEN)),
        ('Naver Cue 점수', '88점', ('90점 (+2)', True, GREEN)),
        ('섹션 첫 문장', '"반도체 산업은 역할에 따라\n크게 네 단계로 나뉩니다."', ('"AI·반도체 밸류체인은 핵심입니다."\n(결론 먼저 → 정의형)', True, GREEN)),
        ('문장 길이', '평균 60~80자', ('평균 30~40자\n(모바일 스캔 최적화)', True, GREEN)),
        ('FAQ 구조', '"Q1. … ### 헤더 + 긴 답변"',
         ('"Q. 한 줄  A. 결론 + 이유"\n(Naver Cue Q&A 추출 최적화)', True, GREEN)),
        ('볼드 처리', '핵심어 일부 적용', '모든 정의 키워드에 볼드 적용\n(AI Overview 인용 최적화)'),
        ('근거', 'GEO 원칙을 학습 데이터에서 적용', ('현재 인용되는 콘텐츠 구조를\n실시간 검색해 적용', True, ORANGE)),
    ],
    col_widths=[3.0, 5.0, 6.0]
)

add_page_break(doc)


# ════════════════════════════════════════════════════════════════
#  4장. 전체 흐름 요약 및 시사점
# ════════════════════════════════════════════════════════════════
heading1(doc, '4장. 전체 흐름 요약 및 시사점')

heading2(doc, '4-1. 전체 파이프라인 흐름')

build_comparison_table(doc,
    headers=['단계', 'Gemini 없음 (1차)', 'Gemini 적용 (2차)', '차이'],
    rows=[
        ('S1\nSonnet', 'Informational 78%', 'Informational 78%', ('동일', False, MID_GRAY)),
        ('S2\nOpus', '추상적 페르소나\n"AI 열풍 투자자"', '구체적 페르소나\n"30~40대 퇴근길 직장인"', ('미세 차이', False, MID_GRAY)),
        ('S3\n★', 'Opus 단독\n시장조사 없음', ('Gemini 웹 검색\n→ 콘텐츠 공백 발견\n→ 구조 재설계', True, GREEN), ('서브토픽 ①⑤\n완전 교체', True, GREEN)),
        ('S4\nOpus×3', '[확인 필요] 5개\n출처 0개', ('[확인 필요] 2개\n출처 3개 추가', True, GREEN), ('신뢰성 향상', True, GREEN)),
        ('S5\n★', 'Opus 폴백\nGEO 86/88점', ('Gemini 검색 기반\nGEO 90/90점', True, GREEN), ('+4/+2점', True, GREEN)),
        ('비용', '$1.24', ('$0.93', True, GREEN), ('-$0.31\n(25% 절감)', True, GREEN)),
    ],
    col_widths=[1.8, 4.2, 4.5, 3.5]
)

heading2(doc, '4-2. 도입 시사점')

body(doc, '이번 테스트를 통해 확인된 핵심 결론입니다:')

bullet(doc, '콘텐츠 차별화의 핵심은 S3 시장조사: Gemini가 실제 웹에서 "한국어 콘텐츠에 없는 것"을 '
           '발견하고, 그 공백을 채우는 구조를 설계하는 것이 품질 차이의 근원입니다.')
bullet(doc, 'GEO 점수 4점 상승의 근거: Opus가 학습 데이터 기반으로 적용하는 GEO 원칙과 '
           'Gemini가 현재 실제 인용 패턴을 검색해 적용하는 원칙 사이의 차이입니다.')
bullet(doc, 'Gemini 비용은 사실상 무시: S3+S5 합산 $0.0011(약 1.5원). '
           '반면 Opus 폴백 시 같은 두 단계에서 $0.43 소요. Gemini는 비용 대비 효과가 절대적입니다.')
bullet(doc, '컴플라이언스 자동화: [확인 필요] 태그와 [출처] 태그가 자동 삽입되어 '
           '금융 규정 위반 리스크를 사전에 차단합니다.')

heading2(doc, '4-3. 다음 단계 제안')

build_comparison_table(doc,
    headers=['과제', '내용', '우선순위'],
    rows=[
        ('Gemini 2.5 Pro 전환', '현재 Flash 사용 중. Pro 전환 시 시장조사 품질 추가 향상 가능\n(현재 계정 무료 한도 초과 상태, 유료 한도 설정 필요)', ('높음', True, ORANGE)),
        ('클러스터 2·3번 생성', '이번 테스트는 클러스터 1만 처리. --top-n 3 옵션으로\n상위 3개 클러스터 원고 동시 생성 가능', ('높음', True, ORANGE)),
        ('자동 스케줄링', '매주 크롤링 완료 후 llm_pipeline 자동 실행\nrun_all.py에 파이프라인 연동', ('중간', False, MID_GRAY)),
        ('사람 검수 프로세스', '[확인 필요] 태그 항목 담당자 검수 후 실제 수치 업데이트\n→ 최종 게시 전 1회 검수로 충분', ('중간', False, MID_GRAY)),
    ],
    col_widths=[3.5, 8.0, 2.5]
)

doc.add_paragraph()
callout_box(doc,
    '📋 결론',
    '이 시스템은 매주 클러스터링 리포트가 생성되는 즉시 블로그 원고 3편을 자동으로 만들어낼 수 있습니다. '
    '1편당 생성 시간 약 3분, 비용 약 $0.93(₩1,300)으로 콘텐츠 마케팅 팀의 작성 부담을 대폭 줄일 수 있으며, '
    'GEO 최적화와 팩트 태깅이 자동으로 이루어져 AI 검색 시대의 콘텐츠 경쟁력을 확보할 수 있습니다.'
)

# ── 저장 ─────────────────────────────────────────────────────────
out_path = r'C:\Windows\system32\project\etf crolling\output\ETF_파이프라인_도입보고서_20260422.docx'
doc.save(out_path)
print(f'저장 완료: {out_path}')
