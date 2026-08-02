# Argus RAG Studio — 이미지 빌드 매트릭스 (단일 진실원천)
# 이름 규약: <REGISTRY>/argus-rag-studio-<kind>:<VERSION>[-<variant>]  (배포 카탈로그와 정합)
#
# 사용:
#   make images                      # 로컬(현재 아키, --load)
#   make images-push                 # 멀티아키 빌드 + 레지스트리 push
#   make image KIND=embedding VARIANT=gpu
#   VERSION=0.4.2 REGISTRY=zot.airgap.local:5000/argus docker buildx bake --push
#
# 변형×아키:
#   cpu/단일      : amd64 + arm64
#   gpu(onnx)     : amd64 전용 (onnxruntime-gpu aarch64 휠 없음) — embedding/reranker
#   gpu-torch     : amd64 + arm64 (torch cu128, DGX Spark/Blackwell) — embedding/reranker
#   detection gpu : amd64 + arm64 (torch easyocr)

variable "REGISTRY"  { default = "" }     # 예: "zot.airgap.local:5000/argus"
variable "VERSION"   { default = "dev" }
# 단일 리포 모드(Docker Hub 등 리포 1개에 태그로 구분): <FLAT_REPO>:<name>-<tag>
# 예: FLAT_REPO=datadynamics/argus-rag-studio → argus-rag-studio:backend-0.1.1
variable "FLAT_REPO" { default = "" }

function "ref" {
  params = [name, tag]
  result = FLAT_REPO != "" ? "${FLAT_REPO}:${name}-${tag}" : (REGISTRY == "" ? "argus-rag-studio-${name}:${tag}" : "${REGISTRY}/argus-rag-studio-${name}:${tag}")
}

group "default" {
  targets = [
    "backend", "hwp",
    "embedding", "embedding-gpu", "embedding-gpu-torch",
    "reranker", "reranker-gpu", "reranker-gpu-torch",
    "detection", "detection-gpu",
  ]
}

# --- backend (backend/Dockerfile, 단일 — API·워커 겸용, command 로 분기) ---
target "backend" {
  context    = "backend"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = [ref("backend", VERSION), ref("backend", "latest")]
}

# --- hwp_render (Node, 단일) ---
target "hwp" {
  context    = "extensions/hwp_render_server"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = [ref("hwp-render-server", VERSION), ref("hwp-render-server", "latest")]
}

# --- embedding ---
target "embedding" {
  context    = "extensions/embedding_server"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = [ref("embedding-server", VERSION), ref("embedding-server", "latest")]
}
target "embedding-gpu" {
  context    = "extensions/embedding_server"
  dockerfile = "Dockerfile.gpu"
  platforms  = ["linux/amd64"]
  tags       = [ref("embedding-server", "${VERSION}-gpu"), ref("embedding-server", "latest-gpu")]
}
target "embedding-gpu-torch" {
  context    = "extensions/embedding_server"
  dockerfile = "Dockerfile.gpu-torch"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = [ref("embedding-server", "${VERSION}-gpu-torch"), ref("embedding-server", "latest-gpu-torch")]
}

# --- reranker ---
target "reranker" {
  context    = "extensions/reranker_server"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = [ref("reranker-server", VERSION), ref("reranker-server", "latest")]
}
target "reranker-gpu" {
  context    = "extensions/reranker_server"
  dockerfile = "Dockerfile.gpu"
  platforms  = ["linux/amd64"]
  tags       = [ref("reranker-server", "${VERSION}-gpu"), ref("reranker-server", "latest-gpu")]
}
target "reranker-gpu-torch" {
  context    = "extensions/reranker_server"
  dockerfile = "Dockerfile.gpu-torch"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = [ref("reranker-server", "${VERSION}-gpu-torch"), ref("reranker-server", "latest-gpu-torch")]
}

# --- detection (gpu = torch/easyocr, amd64+arm64) ---
target "detection" {
  context    = "extensions/detection_server"
  dockerfile = "Dockerfile"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = [ref("detection-server", VERSION), ref("detection-server", "latest")]
}
target "detection-gpu" {
  context    = "extensions/detection_server"
  dockerfile = "Dockerfile.gpu"
  platforms  = ["linux/amd64", "linux/arm64"]
  tags       = [ref("detection-server", "${VERSION}-gpu"), ref("detection-server", "latest-gpu")]
}
