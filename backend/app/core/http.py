# SPDX-License-Identifier: Apache-2.0
"""아웃바운드 HTTP 공용 헬퍼.

OpenAI 호환 외부 서버(임베딩/LLM/리랭커)에 붙일 때, 대부분은 표준
``Authorization: Bearer <key>`` 를 쓰지만 일부 게이트웨이는 다른 헤더를 요구한다
(예: ``X-API-Key: <key>``). 서비스별 ``auth_header``/``auth_scheme`` 설정으로 교체한다.
"""


def auth_headers(
    api_key: str | None,
    header_name: str = "Authorization",
    scheme: str = "Bearer",
) -> dict[str, str]:
    """인증 헤더 딕셔너리를 만든다(키가 없으면 빈 dict).

    - 표준: ``auth_headers(key)`` → ``{"Authorization": "Bearer <key>"}``
    - 스킴 없는 커스텀 헤더: ``auth_headers(key, "X-API-Key", "")`` → ``{"X-API-Key": "<key>"}``

    빈 header_name(공백 포함)이면 인증 헤더를 생략한다(무인증 서버).
    """
    if not api_key:
        return {}
    if header_name is None:
        header_name = "Authorization"
    name = header_name.strip()
    if not name:  # 명시적 빈 헤더 이름 → 인증 헤더 생략(무인증)
        return {}
    prefix = (scheme or "").strip()
    value = f"{prefix} {api_key}" if prefix else api_key
    return {name: value}
