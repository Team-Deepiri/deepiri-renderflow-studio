#!/usr/bin/env bash
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/services/orchestrator/app/gen"
mkdir -p "$OUT"
python3 -m grpc_tools.protoc \
  -I"$ROOT/proto/grpc" \
  --python_out="$OUT" \
  --grpc_python_out="$OUT" \
  "$ROOT/proto/grpc/renderflow.proto"
echo "Generated Python gRPC stubs in $OUT"
