# SPDX-License-Identifier: Apache-2.0
"""Argus 임베딩 모델 파인튜닝 트레이너(참조 구현).

Argus RAG Studio 가 내보낸 학습 데이터셋을 입력으로 받아 임베딩 모델을 파인튜닝하고,
모델 아티팩트 + metadata.json 을 출력한다. 학습은 이 외부 프로그램이 담당하고, 데이터
관리·평가는 Argus 가 담당한다.
"""

__version__ = "0.1.0"
