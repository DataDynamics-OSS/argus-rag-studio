# SPDX-License-Identifier: Apache-2.0
"""사용자 정의 PII 함수 샌드박스 — AST 검증 + 별도 프로세스 실행.

방어선(다층):
  1) AST 검증 — import/이중밑줄 속성/위험 빌트인 차단(저장 시·실행 시 모두).
  2) 제한된 builtins — 화이트리스트만 노출(open/exec/eval/__import__ 등 제거).
  3) 별도 프로세스 — RLIMIT_CPU/AS 자원 제한 + 부모의 벽시계 timeout 강제 kill.
주의: OS 레벨 네트워크 차단(seccomp 등)은 포함하지 않는다. import 차단으로 socket 접근 자체를 막지만,
완전 격리가 필요하면 인제스천 워커를 네트워크/FS 제한 컨테이너에서 실행하십시오.
"""

import ast
import json
import subprocess
import sys

# 함수 계약: 이 이름의 함수를 정의해야 한다.
ENTRY = "redact"

# 차단 이름(빌트인/위험 함수). 속성 접근(__...__)·import 는 별도로 막는다.
_FORBIDDEN = {
    "eval", "exec", "compile", "open", "__import__", "input", "globals", "locals",
    "vars", "getattr", "setattr", "delattr", "dir", "help", "exit", "quit",
    "breakpoint", "memoryview", "classmethod", "staticmethod", "super", "type",
    "object", "property", "__build_class__",
}

# 허용 빌트인 화이트리스트.
_SAFE_BUILTIN_NAMES = [
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "format",
    "frozenset", "int", "isinstance", "issubclass", "len", "list", "map", "max",
    "min", "range", "repr", "reversed", "round", "set", "sorted", "str", "sum",
    "tuple", "zip", "ord", "chr", "hex", "bin", "True", "False", "None",
]


def safe_builtins() -> dict:
    import builtins as _b
    return {n: getattr(_b, n) for n in _SAFE_BUILTIN_NAMES if hasattr(_b, n)}


def validate_code(code: str) -> str | None:
    """정적 검증 — 통과하면 None, 위반이면 오류 메시지(문자열)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"문법 오류: {e}"
    has_entry = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "import 는 허용되지 않습니다(필요한 도구는 re·luhn_ok·bizno_ok·rrn_ok 로 제공)."
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"이중밑줄 속성 접근은 금지됩니다: {node.attr}"
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN:
            return f"허용되지 않는 이름: {node.id}"
        if isinstance(node, ast.FunctionDef) and node.name == ENTRY:
            has_entry = True
    if not has_entry:
        return f"{ENTRY}(text) 함수를 정의해야 합니다."
    return None


def run_function(code: str, text: str, timeout_ms: int = 2000, mem_mb: int = 1024) -> tuple[str | None, str | None]:
    """샌드박스(별도 프로세스)에서 code 의 redact(text) 를 실행한다.

    반환: (결과 문자열, 오류 메시지). 성공 시 (out, None), 실패/타임아웃 시 (None, err).
    """
    err = validate_code(code)
    if err:
        return None, err
    cpu_sec = max(1, int(timeout_ms / 1000) + 1)
    payload = json.dumps({"code": code, "text": text, "cpu_sec": cpu_sec, "mem_mb": mem_mb})
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.pii.sandbox_runner"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout_ms / 1000),
        )
    except subprocess.TimeoutExpired:
        return None, f"실행 시간 초과({timeout_ms}ms)"
    if proc.returncode != 0 and not proc.stdout:
        if proc.returncode < 0:
            return None, f"실행이 자원 제한으로 종료되었습니다(CPU/메모리/시간 초과, signal {-proc.returncode})"
        return None, f"실행 실패: {(proc.stderr or '')[:300] or 'returncode ' + str(proc.returncode)}"
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None, f"실행 결과 파싱 실패: {(proc.stderr or proc.stdout or '')[:300]}"
    if "error" in out:
        return None, out["error"]
    return out.get("result", ""), None
