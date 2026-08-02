# SPDX-License-Identifier: Apache-2.0
"""파인튜닝(Fine-tuning) 모듈.

학습 연산은 외부 프로그램(extensions/retrieval-fine-tuning)이 담당하고, 이 모듈은
학습 입력 데이터(학습 데이터셋)를 관리하고 외부 트레이너 계약(JSONL + manifest)에 맞춰
내보낸다. 설계: design/fine-tuning.md
"""
