# SPDX-License-Identifier: Apache-2.0
"""tests/fixtures/table.pdf 재생성 스크립트(결정적).

커밋된 table.pdf 는 이 스크립트의 산출물이다. 내용을 바꾸려면 여기서 수정 후
``python tests/fixtures/generate.py`` 로 재생성한다. reportlab 필요(dev 의존성).

table.pdf 구성:
    - 제목 "2026 Annual Report" + 헤딩(Overview/Quarterly Results) + 본문 단락
    - 격자선 4×3 표(분기별 Revenue/Growth) — pdfplumber 표 추출 + docling 텍스트 경로용
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = Path(__file__).with_name("table.pdf")


def build() -> None:
    styles = getSampleStyleSheet()
    rows = [
        ["Quarter", "Revenue", "Growth"],
        ["Q1", "100", "5%"],
        ["Q2", "120", "20%"],
        ["Q3", "150", "25%"],
    ]
    table = Table(rows)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    SimpleDocTemplate(str(OUT), pagesize=letter).build([
        Paragraph("2026 Annual Report", styles["Title"]),
        Spacer(1, 12),
        Paragraph("Overview", styles["Heading1"]),
        Paragraph(
            "This report summarizes quarterly revenue and growth for fiscal year 2026.",
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph("Quarterly Results", styles["Heading1"]),
        Spacer(1, 6),
        table,
    ])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
