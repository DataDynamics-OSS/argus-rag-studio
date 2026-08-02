# SPDX-License-Identifier: Apache-2.0
"""사용자 정의 라우팅 함수 샌드박스 — AST 검증 + 별도 프로세스 실행(Phase 3).

PII 함수 샌드박스(app/pii/sandbox.py)와 동일한 다층 방어를 미러링한다:
  1) AST 검증 — import/이중밑줄 속성/위험 빌트인 차단(저장·실행 시 모두).
  2) 제한된 builtins — 화이트리스트만 노출.
  3) 별도 프로세스 — RLIMIT_CPU/AS + 부모의 벽시계 timeout 강제 kill.

함수 계약: ``def route(doc: dict) -> int | None | tuple[int, float]``
  - doc: {filename, metadata, lead_text, source_path, storage, source_type}
  - 반환: 컬렉션 id(확신도 기본값), (id, 0~1 확신도), 해당 없으면 None/0.
코드는 라우팅 정책 stage config 에 저장된다 — 정책 버전과 함께 불변·롤백된다
(PII 처럼 별도 테이블을 두지 않는 이유: 정책이 이미 버전 자산).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys

from app.pii.sandbox import _FORBIDDEN  # 동일 차단 목록 재사용

ENTRY = "route"


def validate_code(code: str) -> str | None:
    """정적 검증 — 통과하면 None, 위반이면 오류 메시지."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"문법 오류: {e}"
    has_entry = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "import 는 허용되지 않습니다(re 는 기본 제공)."
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"이중밑줄 속성 접근은 금지됩니다: {node.attr}"
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN:
            return f"허용되지 않는 이름: {node.id}"
        if isinstance(node, ast.FunctionDef) and node.name == ENTRY:
            has_entry = True
    if not has_entry:
        return f"{ENTRY}(doc) 함수를 정의해야 합니다."
    return None


def run_route_function(
    code: str, doc: dict, timeout_ms: int = 2000, mem_mb: int = 512
) -> tuple[dict | None, str | None]:
    """샌드박스(별도 프로세스)에서 route(doc) 를 실행한다.

    반환: ({"id": int|None, "score": float|None}, None) 또는 (None, 오류).
    """
    err = validate_code(code)
    if err:
        return None, err
    cpu_sec = max(1, int(timeout_ms / 1000) + 1)
    payload = json.dumps({"code": code, "doc": doc, "cpu_sec": cpu_sec, "mem_mb": mem_mb})
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.routing.sandbox_runner"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout_ms / 1000),
        )
    except subprocess.TimeoutExpired:
        return None, f"실행 시간 초과({timeout_ms}ms)"
    if proc.returncode != 0 and not proc.stdout:
        if proc.returncode < 0:
            return None, f"자원 제한으로 종료(signal {-proc.returncode})"
        return None, f"실행 실패: {(proc.stderr or '')[:300] or 'returncode ' + str(proc.returncode)}"
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None, f"실행 결과 파싱 실패: {(proc.stderr or proc.stdout or '')[:300]}"
    if "error" in out:
        return None, out["error"]
    return out.get("result") or {}, None
