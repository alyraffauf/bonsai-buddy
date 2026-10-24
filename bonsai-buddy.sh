if [[ "${1:-}" == "--help" || "${1:-}" == "--version" ]]; then
  exec @llamaServer@ "$@"
fi

model_size="@modelSize@"
runtime_backend="@backend@"
case "$model_size" in
  9b)
    model_name="Ternary-Bonsai-2-9B"
    projector_sha256="e0cb6f6988cea323ef798cd77d019bbb819af75582f034eaab0e7232314953db"
    sampling_arguments=(--min-p 0.0 --presence-penalty 1.0 --repeat-last-n 64)
    ;;
  27b)
    model_name="Ternary-Bonsai-2-27B"
    projector_sha256="6807ede61d570bb86ba34b756a0fa109edc33668604de867c6ea6d8f1d631903"
    sampling_arguments=(--min-p 0.05 --presence-penalty 0.0
      --chat-template-kwargs '{"reasoning_effort":"medium"}'
      --reasoning-effort-allow 'none,medium,xhigh' --reasoning-effort-fallback medium)
    ;;
  *)
    echo "Unsupported model size: $model_size" >&2
    exit 2
    ;;
esac

model_file="@modelFile@"
model_sha256="@modelSha256@"
draft_file="@draftFile@"
speculative_arguments=( @extraArgs@ )
model_directory="${BONSAI_BUDDY_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsai-buddy/models}"
model_repository="https://huggingface.co/prism-ml/$model_name-gguf/resolve/main"
projector_file="$model_name-mmproj-Q8_0.gguf"
mkdir -p "$model_directory"

download_path=""
trap 'if [[ -n "$download_path" ]]; then rm -f -- "$download_path"; fi' EXIT

download_model() {
  local filename="$1"
  local expected_sha256="$2"
  local model_path="$model_directory/$filename"

  if [[ -s "$model_path" ]]; then
    return
  fi

  download_path="$(mktemp "$model_path.part.XXXXXX")"
  echo "Downloading $filename" >&2
  curl --fail --location --retry 3 \
    --output "$download_path" "$model_repository/$filename"
  if ! printf '%s  %s\n' "$expected_sha256" "$download_path" | sha256sum --check --status; then
    echo "Checksum mismatch for $filename" >&2
    exit 1
  fi
  mv -- "$download_path" "$model_path"
  download_path=""
}

download_model "$model_file" "$model_sha256"
download_model "$projector_file" "$projector_sha256"
if [[ -n "$draft_file" ]]; then
  download_model "$draft_file" "@draftSha256@"
  speculative_arguments+=(--model-draft "$model_directory/$draft_file")
fi

fit_target="${BONSAI_BUDDY_GPU_RESERVE_MB:-@gpuReserveMb@}"
if [[ ! "$fit_target" =~ ^[0-9]+$ ]]; then
  echo 'BONSAI_BUDDY_GPU_RESERVE_MB must be a nonnegative integer.' >&2
  exit 2
fi
# HIP reports memory available to its allocator without subtracting desktop VRAM.
# On single-GPU systems, account for physical usage before fitting the model.
vram_usage_files=(/sys/class/drm/card[0-9]*/device/mem_info_vram_used)
if [[ "$runtime_backend" == rocm && ${#vram_usage_files[@]} -eq 1 && -r "${vram_usage_files[0]}" ]]; then
  if desktop_vram_mb=$(HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION-10.3.0}" \
      @vramHelper@ @hipLibrary@ "${vram_usage_files[0]}") && [[ "$desktop_vram_mb" =~ ^[0-9]+$ ]]; then
    fit_target=$((fit_target + desktop_vram_mb))
  else
    read -r used_vram_bytes < "${vram_usage_files[0]}"
    fit_target=$((fit_target + (used_vram_bytes + 1048575) / 1048576))
  fi
fi

exec @llamaServer@ \
  --model "$model_directory/$model_file" \
  --mmproj "$model_directory/$projector_file" \
  --no-mmproj-offload --image-max-tokens 1024 \
  --host 127.0.0.1 --port "${BONSAI_BUDDY_PORT:-8080}" --cors-origins localhost \
  --alias "bonsai2:$model_size" \
  --ctx-size "${BONSAI_BUDDY_CTX:-@contextTokens@}" --parallel 1 \
  --cache-type-k "${BONSAI_BUDDY_KV_TYPE:-@kvType@}" --cache-type-v "${BONSAI_BUDDY_KV_TYPE:-@kvType@}" \
  --reasoning-format deepseek --reasoning-budget "${BONSAI_BUDDY_THINK_TOKENS:-1024}" \
  --reasoning-budget-message $'\nI have enough information. I will now give the final answer or next tool call.\n' \
  --n-predict "${BONSAI_BUDDY_MAX_TOKENS:-@maxTokens@}" \
  --fit on --fit-target "$fit_target" --flash-attn on \
  --batch-size @batchSize@ --ubatch-size @ubatchSize@ --cache-ram "${BONSAI_BUDDY_CACHE_MB:-1024}" \
  --ctx-checkpoints 32 --cache-prompt \
  --temp 1.0 --top-p 0.95 --top-k 20 --repeat-penalty 1.0 \
  "${sampling_arguments[@]}" "${speculative_arguments[@]}" "$@"
