# SPDX-License-Identifier: Apache-2.0
"""PII 사용자 함수 샌드박스 자식 프로세스.

stdin(JSON): {code, text, cpu_sec, mem_mb} → stdout(JSON): {result} 또는 {error}.
신뢰되지 않는 것은 ``code`` 뿐이며, 제한된 builtins + 자원 제한 하에서 실행한다.
``python -m app.pii.sandbox_runner`` 로 부모(app.pii.sandbox)가 호출한다.
"""

import json
import re
import sys


def _limit(cpu_sec: int, mem_mb: int) -> None:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec))
        if mem_mb:
            b = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
    except Exception:  # noqa: BLE001 — 자원 제한 미지원 OS 면 best-effort
        pass


def main() -> None:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print(json.dumps({"error": "입력 파싱 실패"}))
        return
    code = req.get("code") or ""
    text = req.get("text") or ""
    _limit(int(req.get("cpu_sec", 2)), int(req.get("mem_mb", 1024)))

    from app.pii.checks import bizno_ok, luhn_ok, rrn_ok
    from app.pii.sandbox import ENTRY, safe_builtins, validate_code

    err = validate_code(code)
    if err:
        print(json.dumps({"error": err}))
        return

    g = {
        "__builtins__": safe_builtins(),
        "re": re,
        "luhn_ok": luhn_ok, "bizno_ok": bizno_ok, "rrn_ok": rrn_ok,
    }
    try:
        exec(compile(code, "<pii_function>", "exec"), g)  # noqa: S102 — 샌드박스 내 의도된 실행
        fn = g.get(ENTRY)
        if not callable(fn):
            print(json.dumps({"error": f"{ENTRY}(text) 함수를 정의하세요."}))
            return
        out = fn(text)
        if not isinstance(out, str):
            print(json.dumps({"error": f"{ENTRY} 는 문자열을 반환해야 합니다(받음: {type(out).__name__})."}))
            return
        print(json.dumps({"result": out[:1_000_000]}))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))


if __name__ == "__main__":
    main()
