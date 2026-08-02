# SPDX-License-Identifier: Apache-2.0
"""파인튜닝 트레이너 CLI — Argus 와의 입출력 계약을 잇는 진입점.

서브커맨드:
    validate  데이터셋(manifest + train/valid jsonl)을 검증만 한다(학습 의존성 불필요).
    train     데이터셋으로 임베딩 모델을 파인튜닝하고 모델 + metadata.json 을 내보낸다.

예:
    python -m finetune validate --dataset ./samples/dataset
    python -m finetune train --dataset ./samples/dataset --output ./out/tax-law-v1 \
        --base-model intfloat/multilingual-e5-large --epochs 3 --batch-size 32
"""

from __future__ import annotations

import argparse
import logging
import sys

from finetune.dataset import load_split
from finetune.schema import load_manifest


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def cmd_validate(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.dataset)
    train = load_split(args.dataset, "train")
    valid = load_split(args.dataset, "valid")
    print(f"✓ manifest: dataset_id={manifest.dataset_id} base_model={manifest.base_model} "
          f"dim={manifest.embedding_dim} task={manifest.task} prompt={manifest.prompt_format}")
    print(f"✓ train: {len(train)}건  valid: {len(valid)}건")
    with_neg = sum(1 for r in train if r.negatives)
    print(f"  하드네거티브 보유 train 레코드: {with_neg}/{len(train)}")
    if valid:
        print("  (valid 가 있어 학습 후 IR 평가를 수행합니다)")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    from finetune.export import export_model

    manifest = load_manifest(args.dataset)
    task = args.task or manifest.task  # CLI 가 manifest 를 오버라이드
    train_records = load_split(args.dataset, "train")
    valid_records = load_split(args.dataset, "valid")
    if not train_records:
        print("학습 레코드가 없습니다.", file=sys.stderr)
        return 2

    if task == "reranker":
        from finetune.reranker import evaluate_reranker, train_reranker

        model, info = train_reranker(
            train_records, manifest,
            base_model=args.base_model, epochs=args.epochs, batch_size=args.batch_size,
            lr=args.lr, max_negatives=args.max_negatives, device=args.device,
            use_amp=args.fp16,
        )
        valid_metrics = {}
        if valid_records and not args.no_eval:
            valid_metrics = evaluate_reranker(model, valid_records, k=args.eval_k)
    else:
        from finetune.evaluate import evaluate_ir
        from finetune.trainer import train as run_train

        model, info = run_train(
            train_records, manifest,
            base_model=args.base_model, epochs=args.epochs, batch_size=args.batch_size,
            lr=args.lr, max_negatives=args.max_negatives, device=args.device,
            use_amp=args.fp16,
            checkpoint_steps=args.checkpoint_steps,
            checkpoint_path=(f"{args.output}/checkpoints" if args.checkpoint_steps > 0 else None),
        )
        valid_metrics = {}
        if valid_records and not args.no_eval:
            valid_metrics = evaluate_ir(model, valid_records, manifest, k=args.eval_k)

    meta_path = export_model(model, args.output, manifest, info, valid_metrics, task=task)
    print(f"✓ 학습 완료 (task={task}) → {args.output}")
    print(f"  metadata: {meta_path}")
    if valid_metrics:
        print(f"  valid: {valid_metrics}")
    print("  다음 단계: Argus 모델 레지스트리에 등록 → 홀드아웃 골든셋으로 base 와 비교 평가")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="finetune", description="Argus 임베딩 모델 파인튜닝 트레이너")
    p.add_argument("-v", "--verbose", action="store_true", help="디버그 로그")
    sub = p.add_subparsers(dest="command", required=True)

    pv = sub.add_parser("validate", help="데이터셋 검증(학습 의존성 불필요)")
    pv.add_argument("--dataset", required=True, help="Argus 가 내보낸 데이터셋 디렉터리")
    pv.set_defaults(func=cmd_validate)

    pt = sub.add_parser("train", help="임베딩/리랭커 모델 파인튜닝")
    pt.add_argument("--dataset", required=True, help="데이터셋 디렉터리(manifest + train/valid jsonl)")
    pt.add_argument("--output", required=True, help="모델·metadata.json 출력 디렉터리")
    pt.add_argument("--task", choices=["embedding", "reranker"], default=None,
                    help="학습 대상(미지정 시 manifest.task). reranker 는 cross-encoder 파인튜닝")
    pt.add_argument("--base-model", default=None, help="베이스 모델(미지정 시 manifest.base_model)")
    pt.add_argument("--epochs", type=int, default=3)
    pt.add_argument("--batch-size", type=int, default=32)
    pt.add_argument("--lr", type=float, default=2e-5)
    pt.add_argument("--max-negatives", type=int, default=1, help="레코드당 하드네거티브 수(현재 0/1 지원)")
    pt.add_argument("--device", default=None, help="cuda | cpu | mps (미지정 시 자동)")
    # 대량 학습 — fp16 혼합정밀(기본: CUDA 면 자동 on), 체크포인트
    pt.add_argument("--fp16", dest="fp16", action="store_true", default=None,
                    help="fp16 혼합정밀 강제 ON(GPU 속도↑·메모리↓)")
    pt.add_argument("--no-fp16", dest="fp16", action="store_false",
                    help="fp16 강제 OFF")
    pt.add_argument("--checkpoint-steps", type=int, default=0,
                    help="N스텝마다 체크포인트 저장(임베딩 학습, 장시간 대량 학습용). 0=비활성")
    pt.add_argument("--eval-k", type=int, default=5, help="valid 평가 top-k")
    pt.add_argument("--no-eval", action="store_true", help="학습 후 valid 평가 생략")
    pt.set_defaults(func=cmd_train)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
