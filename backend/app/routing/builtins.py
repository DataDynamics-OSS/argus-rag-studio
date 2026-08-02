# SPDX-License-Identifier: Apache-2.0
"""기본 제공 라우터 — 무비용·결정론적(파일명·메타데이터). Phase 1.

내용 임베딩(content_embedding)·LLM(llm_classify)·사용자 정의 함수(custom_function) 라우터는
Phase 2/3 에서 같은 레지스트리에 추가한다. 새 라우터 = 이 파일에 클래스 1개 + ``@register_router``.
"""

from __future__ import annotations

import os
import re

from app.routing.base import Candidate, RouteContext, RouteInput, Router, register_router


@register_router
class FilenameRule(Router):
    """파일명/경로에 키워드(또는 정규식)가 들어 있으면 지정 컬렉션으로 라우팅한다.

    config 예::

        {"match": "substring",
         "rules": [
            {"keywords": ["제안요청서", "rfp"], "collection_id": 3, "score": 0.9},
            {"keywords": ["회의록", "minutes"], "collection_id": 5}
         ]}

    ``match="regex"`` 면 ``keywords`` 항목을 정규식으로 해석한다(대소문자 무시). 매칭되는 규칙마다
    후보를 하나씩 낸다(점수 미지정 시 0.9). 비교는 소문자 기준.
    """

    id = "filename_rule"
    label = "파일명 규칙"
    description = "파일명/경로의 키워드·정규식으로 컬렉션을 정한다(무비용)."
    config_schema = {
        "type": "object",
        "properties": {
            "match": {"type": "string", "enum": ["substring", "regex"], "default": "substring"},
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "collection_id": {"type": "integer"},
                        "score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.9},
                    },
                    "required": ["keywords", "collection_id"],
                },
            },
        },
    }

    def route(self, doc: RouteInput, cfg: dict, ctx: RouteContext | None = None) -> list[Candidate]:
        name = (doc.filename or "").lower()
        if not name:
            return []
        is_regex = (cfg.get("match") or "substring").lower() == "regex"
        out: list[Candidate] = []
        for rule in (cfg.get("rules") or []):
            cid = rule.get("collection_id")
            if cid is None:
                continue
            score = float(rule.get("score", 0.9))
            for kw in (rule.get("keywords") or []):
                kw_s = str(kw)
                hit = False
                if is_regex:
                    try:
                        hit = re.search(kw_s, name, re.IGNORECASE) is not None
                    except re.error:
                        hit = False
                else:
                    hit = kw_s.lower() in name
                if hit:
                    out.append(Candidate(int(cid), score, f"파일명 매칭: {kw_s}"))
                    break  # 한 규칙당 후보 1개
        return out


@register_router
class ExtensionRule(Router):
    """파일 확장자로 컬렉션을 정한다.

    config 예::

        {"rules": [
            {"extensions": ["pdf"], "collection_id": 3, "score": 0.9},
            {"extensions": ["ppt", "pptx", "key"], "collection_id": 7}
        ]}

    확장자는 점 유무·대소문자를 무시하고 비교한다(``.PDF`` / ``pdf`` 동일). 매칭되는 규칙마다
    후보를 낸다(점수 미지정 시 0.9).
    """

    id = "extension_rule"
    label = "확장자 규칙"
    description = "파일 확장자로 컬렉션을 정한다(무비용)."
    config_schema = {
        "type": "object",
        "properties": {
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "extensions": {"type": "array", "items": {"type": "string"}},
                        "collection_id": {"type": "integer"},
                        "score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.9},
                    },
                    "required": ["extensions", "collection_id"],
                },
            },
        },
    }

    @staticmethod
    def _norm(ext) -> str:
        """확장자 정규화 — 선행 점 제거 + 소문자."""
        return str(ext).strip().lower().lstrip(".")

    def route(self, doc: RouteInput, cfg: dict, ctx: RouteContext | None = None) -> list[Candidate]:
        ext = self._norm(os.path.splitext(doc.filename or "")[1])
        if not ext:
            return []
        out: list[Candidate] = []
        for rule in (cfg.get("rules") or []):
            cid = rule.get("collection_id")
            if cid is None:
                continue
            exts = {self._norm(e) for e in (rule.get("extensions") or [])}
            if ext in exts:
                score = float(rule.get("score", 0.9))
                out.append(Candidate(int(cid), score, f"확장자: .{ext}"))
        return out


def _glob_to_regex(pattern: str) -> str:
    """경로 글롭 → 정규식. ``*``=세그먼트 내, ``**``=디렉터리 통과, ``?``=한 글자.

    fnmatch 는 ``*`` 가 ``/`` 를 넘어 매칭돼(오매칭) 쓰지 않는다. 전체 일치(anchored).
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
            elif pattern[i:i + 2] == "**":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "^" + "".join(out) + "$"


@register_router
class PathRule(Router):
    """소스 내 경로(프리픽스·글롭·정규식)와 스토리지 소스로 컬렉션을 정한다.

    참조 인테이크(스토리지 소스 pull)에서 채워지는 ``doc.source_path``/``doc.storage`` 를 본다 —
    일반 업로드(source_path 없음)에서는 후보를 내지 않는다. config 예::

        {"match": "prefix",
         "rules": [
            {"patterns": ["contracts/", "legal/contracts/"], "storage": "사업부NAS",
             "collection_id": 3, "score": 0.95},
            {"patterns": ["hr/**/policy/*.pdf"], "collection_id": 7}
         ]}

    - ``prefix``: 디렉터리 경계 기준 프리픽스("contracts" 는 "contracts-old/…" 미매칭).
    - ``glob``: ``*``=세그먼트 내 / ``**``=디렉터리 통과 / ``?``=한 글자(전체 일치).
    - ``regex``: ``re.search``(부분 일치), 대소문자 무시.
    - ``storage``(선택): 지정 시 해당 소스에서 온 문서만 매칭. 매칭되는 규칙마다 후보 1개
      (규칙 내 첫 패턴 승리, 점수 미지정 시 0.95). 비교는 소문자 기준.
    """

    id = "path_rule"
    label = "경로 규칙"
    description = "스토리지 소스 내 경로(프리픽스·글롭·정규식)로 컬렉션을 정한다(무비용)."
    config_schema = {
        "type": "object",
        "properties": {
            "match": {"type": "string", "enum": ["prefix", "glob", "regex"], "default": "prefix"},
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "patterns": {"type": "array", "items": {"type": "string"}},
                        "storage": {"type": "string"},  # 소스 논리명(선택 — 비우면 모든 소스)
                        "collection_id": {"type": "integer"},
                        "score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.95},
                    },
                    "required": ["patterns", "collection_id"],
                },
            },
        },
    }

    @staticmethod
    def _norm(path: str) -> str:
        """패턴/경로 정규화 — 구분자 통일 + 선행 '/' 제거 + 소문자."""
        return str(path).replace("\\", "/").strip().lstrip("/").lower()

    def _hit(self, mode: str, pattern: str, path: str) -> bool:
        if mode == "regex":
            try:
                return re.search(pattern, path, re.IGNORECASE) is not None
            except re.error:
                return False
        pat = self._norm(pattern)
        if not pat:
            return False
        if mode == "glob":
            return re.match(_glob_to_regex(pat), path) is not None
        # prefix — 디렉터리 경계 기준(패턴 끝 '/' 유무 무관).
        return path == pat or path.startswith(pat if pat.endswith("/") else pat + "/")

    def route(self, doc: RouteInput, cfg: dict, ctx: RouteContext | None = None) -> list[Candidate]:
        path = self._norm(doc.source_path or "")
        if not path:
            return []
        mode = (cfg.get("match") or "prefix").lower()
        storage = (doc.storage or "").strip().lower()
        out: list[Candidate] = []
        for rule in (cfg.get("rules") or []):
            cid = rule.get("collection_id")
            if cid is None:
                continue
            want = str(rule.get("storage") or "").strip().lower()
            if want and want != storage:
                continue
            score = float(rule.get("score", 0.95))
            for pattern in (rule.get("patterns") or []):
                if self._hit(mode, str(pattern), path):
                    reason = f"경로 매칭: {pattern}"
                    if want:
                        reason += f" (소스={rule.get('storage')})"
                    out.append(Candidate(int(cid), score, reason))
                    break  # 한 규칙당 후보 1개
        return out


@register_router
class MetadataMatch(Router):
    """문서 메타데이터(분류 결과 포함) 필드 값으로 컬렉션을 정한다.

    ``metadata`` 는 인제스천 메타추출 + 자동분류 결과(doc_type/dept/source_system/language/author 등).
    config 예::

        {"rules": [
            {"field": "doc_type", "equals": "rfp", "collection_id": 3, "score": 0.85},
            {"field": "dept", "equals": "법무", "collection_id": 5}
        ]}

    비교는 문자열 소문자 동일성(equals). 매칭되는 규칙마다 후보를 낸다(점수 미지정 시 0.8).
    """

    id = "metadata_match"
    label = "메타데이터 매칭"
    description = "doc_type·dept·source_system 등 메타데이터 값으로 컬렉션을 정한다(무비용)."
    config_schema = {
        "type": "object",
        "properties": {
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string"},
                        "equals": {"type": "string"},
                        "collection_id": {"type": "integer"},
                        "score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.8},
                    },
                    "required": ["field", "equals", "collection_id"],
                },
            },
        },
    }

    def route(self, doc: RouteInput, cfg: dict, ctx: RouteContext | None = None) -> list[Candidate]:
        meta = doc.metadata or {}
        out: list[Candidate] = []
        for rule in (cfg.get("rules") or []):
            field = rule.get("field")
            cid = rule.get("collection_id")
            if not field or cid is None or "equals" not in rule:
                continue
            val = meta.get(field)
            if val is None:
                continue
            if str(val).strip().lower() == str(rule["equals"]).strip().lower():
                score = float(rule.get("score", 0.8))
                out.append(Candidate(int(cid), score, f"{field}={rule['equals']}"))
        return out


@register_router
class ContentEmbedding(Router):
    """선두 텍스트 임베딩을 컬렉션 라우팅 디스크립터(centroid)와 비교한다(Phase 2).

    임베딩·프로파일 로딩은 호출부(decide)가 준비해 ctx 로 넘긴다 — 이 라우터는
    코사인 계산만 하는 순수 함수다(테스트 용이). 프로파일이 없거나(미계산·공간 불일치)
    선두 텍스트가 없으면 후보를 내지 않는다(다음 단계로 자연 통과).

    config::

        {"min_similarity": 0.3,   # 코사인 하한(-1~1) — 미만은 후보 제외
         "top_k": 3}              # 상위 몇 개 컬렉션을 후보로 낼지

    점수는 코사인을 0~1 로 사상((cos+1)/2). weighted_vote 조합에서 다른 라우터와
    합산 가능한 스케일이다.
    """

    id = "content_embedding"
    label = "내용 임베딩"
    description = "선두 텍스트 임베딩 vs 컬렉션 디스크립터(centroid) 유사도로 라우팅한다(임베딩 1회)."
    config_schema = {
        "type": "object",
        "properties": {
            "min_similarity": {
                "type": "number", "minimum": -1, "maximum": 1, "default": 0.3,
                "description": "코사인 유사도 하한 — 미만이면 후보 제외",
            },
            "top_k": {"type": "integer", "minimum": 1, "default": 3},
        },
    }

    def route(self, doc: RouteInput, cfg: dict, ctx: RouteContext | None = None) -> list[Candidate]:
        if ctx is None or not ctx.lead_embedding or not ctx.profiles:
            return []
        q = ctx.lead_embedding
        try:
            min_sim = float(cfg.get("min_similarity", 0.3))
        except (TypeError, ValueError):
            min_sim = 0.3
        try:
            top_k = max(1, int(cfg.get("top_k", 3)))
        except (TypeError, ValueError):
            top_k = 3

        scored: list[tuple[float, dict]] = []
        for p in ctx.profiles:
            c = p.get("centroid") or []
            if len(c) != len(q):
                continue  # 공간 불일치 프로파일(방어 — 호출부가 걸러서 옴)
            cos = sum(a * b for a, b in zip(q, c))  # 양쪽 L2 정규화 → 내적=코사인
            if cos >= min_sim:
                scored.append((cos, p))
        scored.sort(key=lambda x: -x[0])
        return [
            Candidate(
                int(p["collection_id"]),
                (cos + 1.0) / 2.0,
                f"cos={cos:.3f} ({p.get('source', 'chunks')})",
            )
            for cos, p in scored[:top_k]
        ]


# ── llm_classify (Phase 3) — 프롬프트 구성/응답 파싱은 순수 함수로 분리(테스트 용이) ──

LLM_MAX_TEXT_CHARS = 1500  # 프롬프트에 넣는 선두 텍스트 상한


def build_llm_messages(doc: RouteInput, collections: list[dict], max_chars: int) -> list[dict]:
    """zero-shot 분류 프롬프트 — 컬렉션 id·이름·설명 목록 + 문서 신호. 순수 함수."""
    lines = []
    for c in collections:
        desc = (c.get("description") or "").strip()
        lines.append(f"- id={c['id']} | {c.get('name', '')}" + (f" — {desc}" if desc else ""))
    lead = (doc.lead_text or "").strip()[:max_chars]
    parts = [f"파일명: {doc.filename or '(없음)'}"]
    if doc.source_path:
        parts.append(f"경로: {doc.source_path}")
    doc_type = (doc.metadata or {}).get("doc_type")
    if doc_type:
        parts.append(f"분류: {doc_type}")
    if lead:
        parts.append(f"선두 텍스트:\n{lead}")
    user = (
        "다음 문서를 아래 지식베이스 후보 중 **정확히 하나**로 분류하라.\n\n"
        "[지식베이스 후보]\n" + "\n".join(lines) + "\n\n"
        "[문서]\n" + "\n".join(parts) + "\n\n"
        '반드시 JSON 한 줄로만 답하라: {"id": <후보 id 정수>, "confidence": <0~1 소수>}\n'
        "어느 후보에도 맞지 않으면 id 에 0 을 넣어라."
    )
    return [
        {"role": "system", "content": "너는 문서를 지식베이스로 분류하는 라우터다. JSON 외 다른 텍스트를 출력하지 마라."},
        {"role": "user", "content": user},
    ]


def parse_llm_choice(text: str, valid_ids: set[int]) -> tuple[int | None, float]:
    """LLM 응답에서 (컬렉션 id, confidence) 를 관대하게 파싱한다. 실패/무효 id 는 (None, 0)."""
    import json as _json

    m = re.search(r"\{[^{}]*\}", text or "", re.S)
    if not m:
        return None, 0.0
    try:
        obj = _json.loads(m.group(0))
        cid = int(obj.get("id"))
        conf = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError, KeyError):
        return None, 0.0
    if cid not in valid_ids:
        return None, 0.0
    return cid, max(0.0, min(1.0, conf))


@register_router
class LlmClassify(Router):
    """컬렉션 설명 목록을 주고 사내 LLM(zero-shot)이 컬렉션을 고르게 한다(Phase 3).

    내용 유사도(content_embedding)와 달리 컬렉션의 **의도(설명)** 를 언어적으로 추론한다 —
    내용이 비슷해도 용도로 갈리는 경계 케이스, 청크가 없어 centroid 가 빈약한 신규 컬렉션에
    유효하다. 비용이 가장 크므로(LLM 1회, 수 초) 캐스케이드 **최후단**에 두는 것이 정석.

    동기 HTTP 호출을 포함하므로 호출부(decide)가 이 단계가 있는 정책을 스레드에서 실행한다
    (이벤트 루프 비블로킹). 서버 미구성/호출 실패는 빈 후보(_run_stage 가 감쌈 — 폴백 진행).
    """

    id = "llm_classify"
    label = "LLM 분류"
    description = "컬렉션 설명을 근거로 사내 LLM 이 zero-shot 선택(문서당 LLM 1회 — 최후단 권장)."
    config_schema = {
        "type": "object",
        "properties": {
            "server_url": {"type": "string", "description": "OpenAI 호환 서버(비우면 전역 llm 설정)"},
            "model": {"type": "string", "description": "모델명(비우면 전역 llm 설정)"},
            "api_key": {"type": "string", "description": "API 키(비우면 전역 llm 설정)"},
            "max_text_chars": {"type": "integer", "default": LLM_MAX_TEXT_CHARS},
            "timeout": {"type": "number", "default": 30},
        },
    }

    def available(self) -> bool:
        # 전역 llm 설정이 없어도 단계 config 의 server_url/model 오버라이드로 동작할 수 있다 —
        # 미가용 처리(_run_stage 스킵)하면 그 경로가 막히므로 항상 가용. 미구성 시 route 가 빈 후보.
        return True

    def route(self, doc: RouteInput, cfg: dict, ctx: RouteContext | None = None) -> list[Candidate]:
        if ctx is None or not ctx.collections:
            return []
        from app.core.config import settings

        server = (cfg.get("server_url") or settings.llm_server_url or "").strip().rstrip("/")
        model = (cfg.get("model") or settings.llm_model or "").strip()
        api_key = cfg.get("api_key") or settings.llm_api_key or ""
        if not server or not model:
            return []
        try:
            max_chars = int(cfg.get("max_text_chars", LLM_MAX_TEXT_CHARS))
        except (TypeError, ValueError):
            max_chars = LLM_MAX_TEXT_CHARS
        try:
            timeout = float(cfg.get("timeout", 30))
        except (TypeError, ValueError):
            timeout = 30.0

        import httpx

        resp = httpx.post(
            f"{server}/chat/completions",
            json={
                "model": model,
                "messages": build_llm_messages(doc, ctx.collections, max_chars),
                "temperature": 0,
                "max_tokens": 200,
            },
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        cid, conf = parse_llm_choice(text, {int(c["id"]) for c in ctx.collections})
        if cid is None:
            return []
        return [Candidate(cid, conf, f"llm:{model}")]


@register_router
class CustomFunction(Router):
    """관리자가 작성한 Python 함수로 라우팅한다(Phase 3 — 탈출구).

    정형 규칙·유사도로 표현이 안 되는 조직 고유 로직(예: 파일명의 사업번호 파싱)을
    코드 배포 없이 흡수한다. 코드는 stage config 에 저장되어 **정책 버전과 함께
    불변·롤백**된다. 실행은 AST 검증 + 제한 builtins + 별도 프로세스(자원 제한) —
    PII 함수 샌드박스와 동일한 다층 방어(app/routing/sandbox.py).

    함수 계약::

        def route(doc):           # doc: {filename, metadata, lead_text, source_path, storage, ...}
            if "계약" in doc["filename"]:
                return 41                 # 컬렉션 id (확신도는 default_score)
            return None                   # 해당 없음(다음 단계로)
            # 또는 return (41, 0.95)      # (id, 확신도)

    동기 subprocess 호출을 포함하므로 호출부(decide)가 이 단계가 있는 정책을
    스레드에서 실행한다. 반환 id 가 활성 컬렉션에 없으면 무시(안전).
    """

    id = "custom_function"
    label = "사용자 정의 함수"
    description = "Python 함수(route(doc))로 직접 라우팅 — 샌드박스 실행, 규칙으로 안 되는 로직의 탈출구."
    config_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "format": "textarea",
                     "description": "def route(doc) 정의 — import 금지, re 기본 제공"},
            "timeout_ms": {"type": "integer", "default": 2000},
            "default_score": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.9,
                              "description": "함수가 id 만 반환할 때 쓰는 확신도"},
        },
    }

    def route(self, doc: RouteInput, cfg: dict, ctx: RouteContext | None = None) -> list[Candidate]:
        code = (cfg.get("code") or "").strip()
        if not code:
            return []
        from app.routing.sandbox import run_route_function

        try:
            timeout_ms = int(cfg.get("timeout_ms", 2000))
        except (TypeError, ValueError):
            timeout_ms = 2000
        try:
            default_score = float(cfg.get("default_score", 0.9))
        except (TypeError, ValueError):
            default_score = 0.9

        payload = {
            "filename": doc.filename, "metadata": doc.metadata or {},
            "lead_text": doc.lead_text, "source_path": doc.source_path,
            "storage": doc.storage, "source_type": doc.source_type,
        }
        result, err = run_route_function(code, payload, timeout_ms=timeout_ms)
        if err:
            raise RuntimeError(err)  # _run_stage 가 감싸 로깅 — 라우팅은 계속
        cid = (result or {}).get("id")
        if not cid:
            return []
        if ctx is not None and ctx.collections and int(cid) not in {int(c["id"]) for c in ctx.collections}:
            return []  # 활성 컬렉션 밖 id 는 무시(안전)
        score = result.get("score")
        return [Candidate(int(cid), score if score is not None else default_score, "custom_function")]
