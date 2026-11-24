#!/bin/bash
# Build the FOSSLab image file on ANY machine with Apptainer (e.g. a Rocky/Alma
# workstation: sudo dnf install epel-release && sudo dnf install apptainer),
# then copy it to the SL7 server:
#
#   ./build_sif.sh [TAG] [OUTPUT.sif]
#   scp iic-osic-tools_2026.07.sif server:/opt/fosslab/images/
#
# or publish it on a web server and set FOSSLAB_SIF_URL in fosslab.conf.
# Useful when the server lacks the ~45 GB the build needs, or bandwidth.

set -euo pipefail
TAG=${1:-2026.07}
OUT=${2:-iic-osic-tools_$TAG.sif}

command -v apptainer >/dev/null 2>&1 || {
    echo "apptainer is not installed here (EL8+: dnf install epel-release && dnf install apptainer)" >&2
    exit 1
}
export APPTAINER_TMPDIR=${APPTAINER_TMPDIR:-$PWD/.sif-tmp}
mkdir -p "$APPTAINER_TMPDIR"
apptainer build "$OUT" "docker://hpretl/iic-osic-tools:$TAG"
rm -rf "$APPTAINER_TMPDIR"
ls -lh "$OUT"
