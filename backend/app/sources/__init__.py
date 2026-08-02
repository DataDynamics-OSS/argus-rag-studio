# SPDX-License-Identifier: Apache-2.0
"""스토리지 소스 레지스트리 — 참조 인테이크(pull)의 원본 소스(S3·NAS) 등록/접근.

내부 저장소(``app.storage``, 스냅샷·산출물 저장)와 구분되는 **읽기 전용** 소스 계층이다.
소스 접근은 ``SourceAdapter``(stat/read/list 3메서드)로 좁게 정의한다 — 새 소스 종류(kind)
추가 = 어댑터 클래스 1개(라우팅 ``Router`` 레지스트리와 동형 확장 패턴).
"""
