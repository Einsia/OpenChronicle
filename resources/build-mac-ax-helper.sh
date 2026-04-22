#!/usr/bin/env bash
# Compile mac-ax-helper.swift into a native binary.
# Safe to run on non-macOS — exits silently.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${SCRIPT_DIR}/mac-ax-helper.swift"
OUT="${SCRIPT_DIR}/mac-ax-helper"

if [[ ! -f "${SRC}" ]]; then
  echo "[mac-ax-helper] Source not found: ${SRC}" >&2
  exit 1
fi

# Skip rebuild if binary is newer than source
if [[ -f "${OUT}" && "${OUT}" -nt "${SRC}" ]]; then
  echo "[mac-ax-helper] Binary is up to date, skipping compile."
  exit 0
fi

ARCH=$(uname -m)
if [[ "${ARCH}" == "arm64" ]]; then
  TARGET="arm64-apple-macos12.0"
else
  TARGET="x86_64-apple-macos12.0"
fi

CACHE_DIR="/tmp/clang-module-cache"
mkdir -p "${CACHE_DIR}"

echo "[mac-ax-helper] Compiling ${SRC} → ${OUT}"
if ! CLANG_MODULE_CACHE_PATH="${CACHE_DIR}" swiftc \
     "${SRC}" -o "${OUT}" -O -target "${TARGET}" -swift-version 5; then
  echo "[mac-ax-helper] swiftc failed." >&2
  echo "[mac-ax-helper] Install Xcode Command Line Tools: xcode-select --install" >&2
  exit 1
fi

echo "[mac-ax-helper] Done."
