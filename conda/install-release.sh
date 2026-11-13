#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ENV_FILE="$BUNDLE_DIR/conda/environment.yml"
ENV_NAME="${DFTHUB_CONDA_ENV:-dfthub-0.1.1}"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required; install Miniconda or Mambaforge first" >&2
  exit 1
fi

conda env update --name "$ENV_NAME" --file "$ENV_FILE" --prune
CONDA_ENV_PATH="$(conda run -n "$ENV_NAME" python -c 'import sys; print(sys.prefix)')"
conda run -n "$ENV_NAME" python -m pip install \
  --no-index --require-hashes \
  --find-links "$BUNDLE_DIR/wheelhouse" \
  -r "$BUNDLE_DIR/requirements.lock"
conda run -n "$ENV_NAME" dfthub doctor --strict
echo "DFThub installed in conda environment: $ENV_NAME ($CONDA_ENV_PATH)"
echo "Activate it with: conda activate $ENV_NAME"
