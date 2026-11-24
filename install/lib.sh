# Shared helpers for the FOSSLab install scripts (bash 4.2: Scientific Linux 7).
# shellcheck shell=bash

set -o pipefail

INSTALL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SRC_DIR=$(dirname "$INSTALL_DIR")
LOG=${FOSSLAB_INSTALL_LOG:-/var/log/fosslab-install.log}

info() { echo "[fosslab] $*" | tee -a "$LOG" >&2; }
warn() { echo "[fosslab] WARNING: $*" | tee -a "$LOG" >&2; }
die()  { echo "[fosslab] ERROR: $*" | tee -a "$LOG" >&2; exit 1; }

need_root() {
    [ "$(id -u)" -eq 0 ] || die "run this as root (sudo $0)"
}

load_conf() {
    # The installed config wins over the template next to these scripts.
    local conf=${FOSSLAB_CONF:-}
    if [ -z "$conf" ]; then
        if [ -r /etc/fosslab.conf ]; then conf=/etc/fosslab.conf
        else conf=$INSTALL_DIR/fosslab.conf; fi
    fi
    # shellcheck source=/dev/null
    . "$conf" || die "cannot read $conf"
    export FOSSLAB_CONF_USED=$conf
}

el_version() {
    # 7 for SL7/CentOS 7/RHEL 7, 8, 9, ... ; empty if not an EL system
    if [ -r /etc/os-release ]; then
        # shellcheck source=/dev/null
        ( . /etc/os-release; echo "${VERSION_ID%%.*}" )
    elif [ -r /etc/redhat-release ]; then
        sed -n 's/.*release \([0-9]*\).*/\1/p' /etc/redhat-release
    fi
}

os_name() {
    if [ -r /etc/redhat-release ]; then cat /etc/redhat-release; else uname -sr; fi
}

free_gb() {
    # free space (GB) on the filesystem holding $1 (or its nearest parent)
    local d=$1
    while [ ! -d "$d" ]; do d=$(dirname "$d"); done
    df -Pk "$d" | awk 'NR==2 {print int($4/1024/1024)}'
}

run_logged() {
    info "\$ $*"
    "$@" 2>&1 | tee -a "$LOG"
    return "${PIPESTATUS[0]}"
}
