if [[ "${1:-}" == "--help" || "${1:-}" == "--version" ]]; then
  exec @llamaServer@ "$@"
fi

model_size="@modelSize@"
case "$model_size" in
  9b)
    model_name="Ternary-Bonsai-2-9B"
    model_file="$model_name-PQ2_0.gguf"
    model_sha256="7a89ab48f5038c704480f60781f9b8d4035351f5f6beb7d11fad80001fde23f9"
    projector_sha256="e0cb6f6988cea323ef798cd77d019bbb819af75582f034eaab0e7232314953db"
    sampling_arguments=(--min-p 0.0 --presence-penalty 1.0 --repeat-last-n 64)
    ;;
  27b)
    model_name="Ternary-Bonsai-2-27B"
    model_file="$model_name-PTQ1_0.gguf"
    model_sha256="53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3"
    projector_sha256="6807ede61d570bb86ba34b756a0fa109edc33668604de867c6ea6d8f1d631903"
    sampling_arguments=(--min-p 0.05 --presence-penalty 0.0 --chat-template-kwargs '{"reasoning_effort":"medium"}')
    ;;
  *)
    echo "Unsupported model size: $model_size" >&2
    exit 2
    ;;
esac

model_directory="${BONSAI_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsaid/models}"
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

exec @llamaServer@ \
  --model "$model_directory/$model_file" \
  --mmproj "$model_directory/$projector_file" \
  --no-mmproj-offload --image-max-tokens 1024 \
  --host 127.0.0.1 --port "${BONSAI_PORT:-8080}" --cors-origins localhost \
  --alias "bonsai2:$model_size" \
  --ctx-size "${BONSAI_CTX:-8192}" --parallel 1 \
  --fit on --fit-target 512 --flash-attn auto \
  --batch-size 256 --ubatch-size 128 --cache-ram 256 \
  --temp 1.0 --top-p 0.95 --top-k 20 --repeat-penalty 1.0 \
  "${sampling_arguments[@]}" "$@"
