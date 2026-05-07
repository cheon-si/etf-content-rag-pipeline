"""SMTP 이메일 발송기 — 주간 ETF 콘텐츠 브리프 자동 발송.

지원 환경변수 (.env):
    EMAIL_SMTP_HOST      SMTP 서버 호스트 (기본: smtp.gmail.com)
    EMAIL_SMTP_PORT      SMTP 포트 (기본: 587)
    EMAIL_SENDER         발신자 이메일 주소
    EMAIL_PASSWORD       발신자 비밀번호 (Gmail 앱 비밀번호 권장)
    EMAIL_RECIPIENTS     수신자 목록 (쉼표로 구분, 예: a@co.com,b@co.com)
"""
from __future__ import annotations

import logging
import os
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


class EmailSender:
    """SMTP 이메일 발송기. Gmail App Password 또는 일반 SMTP 지원."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        sender: str,
        password: str,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.sender = sender
        self.password = password

    def send_weekly_report(
        self,
        recipients: list[str],
        date_label: str,
        content_brief_html: Path,
        content_ideas_html: Path | None = None,
        cost_summary: str = "",
    ) -> None:
        """주간 콘텐츠 브리프 이메일 발송.

        Args:
            recipients:         수신자 이메일 목록
            date_label:         주차 레이블 (예: "2026년 17주차 (4/22)")
            content_brief_html: 이메일 본문으로 삽입할 HTML 파일 경로
            content_ideas_html: 첨부파일로 보낼 콘텐츠 아이디어 HTML (선택)
            cost_summary:       비용 요약 텍스트 (예: "$0.93 사용")
        """
        subject = f"[ETF 마케팅] {date_label} 주간 콘텐츠 브리프"
        if not recipients:
            logger.warning("[Email] 수신자가 없어 발송 건너뜀")
            return

        # 이메일 구성
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = ", ".join(recipients)

        # 본문: content_brief_report.html 내용 인라인
        body_html = ""
        if content_brief_html.exists():
            body_html = content_brief_html.read_text(encoding="utf-8")
        else:
            logger.warning("[Email] 브리프 HTML 파일 없음: %s", content_brief_html)
            body_html = f"<p>ETF 콘텐츠 브리프 ({date_label})</p>"

        # 비용 정보 푸터 추가
        if cost_summary:
            body_html += (
                f'<p style="color:#aaa;font-size:0.8em;margin-top:16px;">'
                f'이번 실행 LLM 비용: {cost_summary}</p>'
            )

        msg.attach(MIMEText(body_html, "html", "utf-8"))

        # 첨부파일: content_ideas_report.html
        if content_ideas_html and content_ideas_html.exists():
            _attach_file(msg, content_ideas_html, "ETF_콘텐츠_아이디어.html")

        # 발송
        logger.info("[Email] '%s' 발송 시작 → %s", subject, recipients)
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, recipients, msg.as_string())
            logger.info("[Email] 발송 완료")
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "[Email] 인증 실패 — Gmail 사용 시 앱 비밀번호(16자리)를 EMAIL_PASSWORD에 설정하세요."
            )
            raise
        except smtplib.SMTPException as exc:
            logger.error("[Email] SMTP 오류: %s", exc)
            raise


def _attach_file(msg: MIMEMultipart, path: Path, filename: str) -> None:
    """파일을 MIMEMultipart 메시지에 첨부한다."""
    with open(path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        "attachment",
        filename=("utf-8", "", filename),
    )
    msg.attach(part)


def send_weekly_email(
    output_dir: Path | None = None,
    date_label: str | None = None,
    cost_summary: str = "",
) -> None:
    """환경변수에서 설정을 자동 로드해 주간 이메일을 발송한다.

    run_all.py Step 11에서 직접 호출하는 convenience 함수.
    """
    smtp_host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
    sender = os.environ.get("EMAIL_SENDER", "")
    password = os.environ.get("EMAIL_PASSWORD", "")
    recipients_raw = os.environ.get("EMAIL_RECIPIENTS", "")

    if not sender or not password:
        logger.warning(
            "[Email] EMAIL_SENDER 또는 EMAIL_PASSWORD 환경변수 없음 — 이메일 발송 건너뜀"
        )
        return

    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    if not recipients:
        logger.warning("[Email] EMAIL_RECIPIENTS 환경변수 없음 — 이메일 발송 건너뜀")
        return

    # 최신 output 디렉토리 자동 탐지
    if output_dir is None:
        from datetime import datetime
        output_dir = Path("output") / datetime.now().strftime("%Y-%m-%d")

    brief_html = output_dir / "content_brief_report.html"
    ideas_html = output_dir / "content_ideas_report.html"

    if not brief_html.exists():
        logger.warning("[Email] 브리프 HTML 없음: %s — 발송 건너뜀", brief_html)
        return

    if date_label is None:
        from datetime import datetime
        d = datetime.now()
        _, iso_week, _ = d.isocalendar()
        date_label = f"{d.year}년 {iso_week}주차 ({d.month}/{d.day})"

    emailer = EmailSender(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        sender=sender,
        password=password,
    )
    emailer.send_weekly_report(
        recipients=recipients,
        date_label=date_label,
        content_brief_html=brief_html,
        content_ideas_html=ideas_html if ideas_html.exists() else None,
        cost_summary=cost_summary,
    )
