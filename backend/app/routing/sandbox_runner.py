# SPDX-License-Identifier: Apache-2.0
"""라우팅 사용자 함수 샌드박스 자식 프로세스.

stdin(JSON): {code, doc, cpu_sec, mem_mb} → stdout(JSON): {result: {id, score}} 또는 {error}.
신뢰되지 않는 것은 ``code`` 뿐 — 제한된 builtins + 자원 제한 하에서 실행한다.
``python -m app.routing.sandbox_runner`` 로 부모(app.routing.sandbox)가 호출한다.
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
    doc = req.get("doc") or {}
    _limit(int(req.get("cpu_sec", 2)), int(req.get("mem_mb", 512)))

    from app.pii.sandbox import safe_builtins
    from app.routing.sandbox import ENTRY, validate_code

    err = validate_code(code)
    if err:
        print(json.dumps({"error": err}))
        return

    g = {"__builtins__": safe_builtins(), "re": re}
    try:
        exec(compile(code, "<route_function>", "exec"), g)  # noqa: S102 — 샌드박스 내 의도된 실행
        fn = g.get(ENTRY)
        if not callable(fn):
            print(json.dumps({"error": f"{ENTRY}(doc) 함수를 정의하세요."}))
            return
        out = fn(doc)
        # 반환 정규화: None/0 = 해당 없음, int = id, (id, score) 허용.
        cid, score = None, None
        if isinstance(out, (tuple, list)) and len(out) == 2:
            cid, score = out[0], out[1]
        elif out is not None:
            cid = out
        try:
            cid = int(cid) if cid else None
        except (TypeError, ValueError):
            print(json.dumps({"error": f"{ENTRY} 반환값이 올바르지 않습니다: {out!r}"}))
            return
        if score is not None:
            try:
                score = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                score = None
        print(json.dumps({"result": {"id": cid, "score": score}}))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))


if __name__ == "__main__":
    main()
