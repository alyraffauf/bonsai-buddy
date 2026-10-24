if [[ "${1:-}" == --help || "${1:-}" == --version ]]; then
  exec @clientProgram@ "$@"
fi

port="${BONSAI_BUDDY_PORT:-8080}"
context_tokens="${BONSAI_BUDDY_CTX:-@contextTokens@}"
output_tokens="${BONSAI_BUDDY_MAX_TOKENS:-@maxTokens@}"
thinking_tokens="${BONSAI_BUDDY_THINK_TOKENS:-@thinkingTokens@}"
for value in "$port" "$context_tokens" "$output_tokens" "$thinking_tokens"; do
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    echo 'Client launchers require nonnegative integer port and token settings.' >&2
    exit 2
  fi
done
if ((port < 1 || port > 65535 || output_tokens < 1 || context_tokens <= output_tokens || thinking_tokens >= output_tokens)); then
  echo 'Use a valid port and leave room for both the prompt and final answer.' >&2
  exit 2
fi

base_url="http://127.0.0.1:$port"
input_tokens=$((context_tokens - output_tokens))
reserved_tokens=$((input_tokens / 3))
if ((reserved_tokens > @reserveTokens@)); then
  reserved_tokens=@reserveTokens@
fi
temporary_directory=$(mktemp -d -t bonsai-buddy-client.XXXXXX)
server_pid=""

cleanup() {
  if [[ -n "$server_pid" ]]; then
    kill -TERM "$server_pid" 2>/dev/null || true
    for _ in {1..50}; do
      kill -0 "$server_pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf -- "$temporary_directory"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! curl --fail --silent --max-time 2 "$base_url/health" > /dev/null; then
  echo "Starting Bonsai Buddy @modelSize@ on port $port. Build/download log: $temporary_directory/server.log" >&2
  @serverProgram@ > "$temporary_directory/server.log" 2>&1 &
  server_pid=$!
  deadline=$((SECONDS + 1800))
  until curl --fail --silent --max-time 2 "$base_url/health" > /dev/null; do
    if ! kill -0 "$server_pid" 2>/dev/null || ((SECONDS >= deadline)); then
      echo 'The model server did not become ready. Check that the port and GPU are available.' >&2
      tail -n 40 "$temporary_directory/server.log" >&2
      exit 1
    fi
    sleep 1
  done
fi

curl --fail --silent --show-error --max-time 5 "$base_url/props" > "$temporary_directory/props.json"
model_alias=$(jq -r '.model_alias // ""' "$temporary_directory/props.json")
server_context=$(jq -r '.default_generation_settings.n_ctx // 0' "$temporary_directory/props.json")
if [[ "$model_alias" != "bonsai2:@modelSize@" ]] || ! [[ "$server_context" =~ ^[0-9]+$ ]] || ((server_context != context_tokens)); then
  echo "Port $port serves '$model_alias' with $server_context context tokens; this launcher needs bonsai2:@modelSize@ with $context_tokens." >&2
  echo 'Stop that server before switching profiles, or use its matching client launcher.' >&2
  exit 1
fi

jq --arg url "$base_url/v1" --arg model "bonsai2:@modelSize@" \
  --argjson context "$context_tokens" --argjson input "$input_tokens" \
  --argjson output "$output_tokens" --argjson thinking "$thinking_tokens" \
  --argjson reserve "$reserved_tokens" '
    .providers["bonsai-buddy"].settings.baseURL = $url |
    .providers["bonsai-buddy"].models[$model].limit = {context: $context, input: $input, output: $output} |
    .providers["bonsai-buddy"].models[$model].body.reasoning_budget_tokens = $thinking |
    .compaction.buffer = $reserve |
    .compaction.keep.tokens = $reserve
  ' @opencodeConfig@ > "$temporary_directory/opencode.json"
export OPENCODE_CONFIG="$temporary_directory/opencode.json"
@clientProgram@ "$@" --standalone
