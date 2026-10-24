if [[ "${1:-}" == "--help" || "${1:-}" == "--version" ]]; then
  exec @llamaServer@ "$@"
fi

model_directory="${BONSAI_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsaid/models}"
model_repository="https://huggingface.co/prism-ml/Ternary-Bonsai-2-9B-gguf/resolve/main"
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

download_model Ternary-Bonsai-2-9B-PQ2_0.gguf \
  7a89ab48f5038c704480f60781f9b8d4035351f5f6beb7d11fad80001fde23f9
download_model Ternary-Bonsai-2-9B-mmproj-Q8_0.gguf \
  e0cb6f6988cea323ef798cd77d019bbb819af75582f034eaab0e7232314953db

exec @llamaServer@ \
  --model "$model_directory/Ternary-Bonsai-2-9B-PQ2_0.gguf" \
  --mmproj "$model_directory/Ternary-Bonsai-2-9B-mmproj-Q8_0.gguf" \
  --no-mmproj-offload --image-max-tokens 1024 \
  --host 127.0.0.1 --port "${BONSAI_PORT:-8080}" --cors-origins localhost \
  --alias bonsai2:9b \
  --ctx-size "${BONSAI_CTX:-8192}" --parallel 1 \
  --fit on --fit-target 512 --flash-attn auto \
  --batch-size 256 --ubatch-size 128 --cache-ram 256 \
  --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0 \
  --repeat-penalty 1.0 --presence-penalty 1.0 --repeat-last-n 64 "$@"
