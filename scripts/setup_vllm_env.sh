#!/usr/bin/env bash
# Creates the separate "vllm" micromamba env (never mixed with the pipeline env "locx")
# and pre-downloads the model into the HF cache. Idempotent: skips steps already done.
# vLLM 0.32.0+cu129: the server driver (560) supports CUDA <= 12.6; the default PyPI wheels of
# vLLM >= 0.33 are CUDA 13 only (needs driver >= 580). CUDA 12.9 builds run via minor-version
# compatibility.
set -euo pipefail
cd "$(dirname "$0")/.."
VLLM_VERSION="${VLLM_VERSION:-0.32.0}"
CUDA_TAG="${CUDA_TAG:-cu129}"
WHEEL="https://github.com/vllm-project/vllm/releases/download/v${VLLM_VERSION}/vllm-${VLLM_VERSION}+${CUDA_TAG}-cp38-abi3-manylinux_2_28_x86_64.whl"
MODEL="${MODEL:-$(sed -n 's/^ *model: *\([^ #]*\).*/\1/p' config.yaml | head -1)}"
GPU="${GPU:-$(sed -n 's/^ *gpu: *\([0-9]*\).*/\1/p' config.yaml)}"
MM="${MAMBA_EXE:-$HOME/.local/bin/micromamba}"
mkdir -p logs

if ! "$MM" env list | awk '{print $1}' | grep -qx vllm; then
  echo "[setup] creating env vllm (python 3.11)"
  "$MM" create -y -n vllm --override-channels -c conda-forge python=3.11
fi
run() { "$MM" run -n vllm "$@"; }

run python -m pip install -q --upgrade pip "huggingface_hub[cli]"
echo "[setup] model $MODEL (hf download skips files already cached)"
run hf download "$MODEL" > logs/model_download.log 2>&1

if ! run python -c "import vllm, sys; sys.exit(not vllm.__version__.startswith('$VLLM_VERSION'))" 2>/dev/null; then
  echo "[setup] installing vllm $VLLM_VERSION+$CUDA_TAG"
  run python -m pip install "$WHEEL" --extra-index-url "https://download.pytorch.org/whl/$CUDA_TAG"
  # PyPI's latest torchcodec (0.17) is a CUDA 13 build (needs libnvrtc.so.13); vLLM imports it at startup.
  run python -m pip install "torchcodec==0.16.0" --index-url "https://download.pytorch.org/whl/$CUDA_TAG"
fi
CUDA_VISIBLE_DEVICES="$GPU" run python -c "
import torch, vllm, vllm.multimodal
print('[setup] vllm', vllm.__version__, '| torch', torch.__version__, '| torch CUDA', torch.version.cuda)
ok = torch.cuda.is_available()
print('[setup] GPU visible:', ok, '|', torch.cuda.get_device_name(0) if ok else '-')
assert ok, 'torch cannot see the GPU'
"
echo "[setup] done"
