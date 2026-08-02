# SPDX-License-Identifier: Apache-2.0
"""모델 팩 스크립트(외부망) — HF 모델을 에어갭 반입용 아카이브로 패키징.

설계: design/model-packaging.md §3.2. 외부망 머신에서 실행해 아카이브를 만들고,
이미지 반입과 같은 채널로 에어갭에 들여간 뒤 MinIO ``argus-models`` 버킷에 올린다::

    # 매니페스트 항목 팩(카탈로그의 kind/name)
    python -m scripts.pack_model vlm/qwen2-vl-7b --out ./packs

    # 매니페스트 전체(source=hf) 일괄 팩 — 미러링 세트 생성
    python -m scripts.pack_model --all --out ./packs

    # 임의 repo 팩(카탈로그 밖 — 반입 후 설정 extra_models 에 등록)
    python -m scripts.pack_model --repo openbmb/MiniCPM-V-2_6 --kind vlm --out ./packs

    # 반입(에어갭 안, MinIO CLI — 수십 GB 는 화면 업로드 대신 이쪽 권장)
    mc cp packs/vlm/qwen2-vl-7b/<rev>/* local/argus-models/vlm/qwen2-vl-7b/<rev>/

산출물(항목당)::

    <out>/{kind}/{name}/{revision}/model.tar.zst   # zstd 없으면 model.tar.gz
    <out>/{kind}/{name}/{revision}/manifest.json   # repo·revision·sha256·size·target

압축은 zstd CLI 가 있으면 tar.zst, 없으면 tar.gz(파이썬 내장). manifest 의 ``archive``
필드가 실제 파일명을 가리키므로 설치 측은 이를 따른다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    *, kind: str, name: str, repo: str, revision: str, target: str,
    archive: str, sha256: str, size_bytes: int,
) -> dict:
    """설치/보유 확인 측과 공유하는 manifest.json 내용(단일 출처)."""
    return {
        "kind": kind, "name": name, "repo": repo, "revision": revision,
        "target": target, "archive": archive, "sha256": sha256, "size_bytes": size_bytes,
        "format": "model-pack/v1",
    }


def make_archive(src_dir: Path, dest_dir: Path) -> Path:
    """src_dir 를 tar.zst(가능하면) 또는 tar.gz 로 묶는다. 아카이브 경로 반환.

    아카이브 루트는 디렉터리 내용물(전개 시 대상 디렉터리에 바로 풀리는 형태)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which("zstd"):
        tar_path = dest_dir / "model.tar"
        with tarfile.open(tar_path, "w") as tf:
            for item in sorted(src_dir.iterdir()):
                tf.add(item, arcname=item.name)
        out = dest_dir / "model.tar.zst"
        subprocess.run(["zstd", "-q", "-f", "-T0", str(tar_path), "-o", str(out)], check=True)
        tar_path.unlink()
        return out
    out = dest_dir / "model.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        for item in sorted(src_dir.iterdir()):
            tf.add(item, arcname=item.name)
    return out


def pack_one(*, kind: str, name: str, repo: str, revision: str, target: str, out_root: Path) -> Path:
    """모델 1개 팩 — 다운로드 → 아카이브 → manifest. 산출 디렉터리 반환."""
    from huggingface_hub import snapshot_download

    print(f"[pack] {kind}/{name}  ←  {repo}@{revision}")
    with tempfile.TemporaryDirectory(prefix="model-pack-") as tmp:
        snap = snapshot_download(repo_id=repo, revision=revision, local_dir=tmp)
        snap_dir = Path(snap)
        # 실제 스냅샷 commit hash 로 revision 고정(반입 후 재현성 — 설계 열린질문 반영).
        ref = snap_dir / ".cache"  # local_dir 방식은 커밋 정보가 없을 수 있음 — 인자 revision 유지
        resolved_rev = revision
        dest = out_root / kind / name / resolved_rev
        archive = make_archive(snap_dir, dest)
        digest = sha256_of(archive)
        manifest = build_manifest(
            kind=kind, name=name, repo=repo, revision=resolved_rev, target=target,
            archive=archive.name, sha256=digest, size_bytes=archive.stat().st_size,
        )
        (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        print(f"[pack] 완료: {archive}  ({archive.stat().st_size / 1e6:.1f} MB, sha256={digest[:12]}…)")
        print(f"[pack] 반입: mc cp {dest}/* <alias>/argus-models/{kind}/{name}/{resolved_rev}/")
        _ = ref  # (미사용 경고 방지 — commit 고정은 후속)
        return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="에어갭 반입용 모델 팩(외부망 실행). 대상: 매니페스트 kind/name, --all, --repo",
    )
    parser.add_argument("model", nargs="?", help="시드 항목 — 예: vlm/qwen2-vl-7b")
    parser.add_argument("--all", action="store_true", help="시드 전체(source=hf) 일괄 팩")
    parser.add_argument("--repo", help="임의 HF repo 팩 — 레지스트리 등록 모델은 화면이 이 형태의 명령을 복사해 줌")
    parser.add_argument("--kind", default="vlm", help="--repo 사용 시 kind(기본 vlm)")
    parser.add_argument(
        "--name",
        help="--repo 사용 시 논리명(기본: repo 끝 이름 소문자) — 레지스트리 name 과 일치해야 보유로 인식",
    )
    parser.add_argument("--revision", default="main", help="HF revision(기본 main)")
    parser.add_argument("--out", default="./packs", help="산출 디렉터리(기본 ./packs)")
    args = parser.parse_args(argv)

    from app.modelreg.seeds import KIND_TARGETS
    from app.servermgr.model_catalog import list_models, resolve_model

    out_root = Path(args.out)
    targets: list[dict] = []
    if args.all:
        targets = [m for m in list_models() if m["source"] == "hf"]
    elif args.repo:
        name = args.name or args.repo.rsplit("/", 1)[-1].lower()
        targets = [{
            "kind": args.kind, "name": name, "repo": args.repo, "source": "hf",
            # 전개 레이아웃은 kind 로 결정 — vlm/detection: flat(로컬 경로 서빙),
            # embedding/reranker: hf-cache(이름으로 캐시 조회).
            "target": KIND_TARGETS.get(args.kind, "hf-cache"),
        }]
    elif args.model:
        kind, _, name = args.model.partition("/")
        m = resolve_model(kind, name)
        if not m:
            print(f"시드에 없는 모델: {args.model} (python -m scripts.pack_model --repo … 사용)")
            return 1
        if m["source"] != "hf":
            print(f"{args.model} 은 source={m['source']} — 이 스크립트로 팩할 수 없습니다({m.get('note')})")
            return 1
        targets = [m]
    else:
        print("대상 미지정 — 시드 목록(레지스트리 등록 모델은 모델 관리 화면에서 명령 복사):")
        for m in list_models():
            mark = "" if m["source"] == "hf" else f"  [{m['source']} — 수동]"
            print(f"  {m['kind']}/{m['name']:<24} {m['repo']}{mark}")
        return 0

    for m in targets:
        pack_one(
            kind=m["kind"], name=m["name"], repo=m["repo"],
            revision=args.revision, target=m["target"], out_root=out_root,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
