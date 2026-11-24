# container-env.sh -- runs INSIDE the IIC-OSIC-TOOLS image, called by fosslab-run.
#
#   bash container-env.sh TOOL [ARGS...]
#
# Rebuilds the image's own environment (apptainer does not source
# /etc/profile.d), then moves everything the image points at its
# read-only /headless home into the user's real $HOME.

: "${FOSSLAB_PREFIX:?FOSSLAB_PREFIX not set}"
export HOME=${HOME:-/tmp}
export USER=${USER:-$(id -un 2>/dev/null || echo designer)}

# Writable per-user places (the image defaults live in read-only /headless).
export XDG_RUNTIME_DIR=/tmp/fosslab-runtime-$(id -u)
export XDG_DATA_HOME=$HOME/.local/share
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_DATA_HOME" 2>/dev/null
chmod 700 "$XDG_RUNTIME_DIR" 2>/dev/null

# The image's single source of truth for PATH, PYTHONPATH, PDK, ...
export IIC_OSIC_TOOLS_QUIET=1
unset FOSS_INIT_DONE KLAYOUT_PATH SPICE_USERINIT_DIR PDK PDKPATH STD_CELL_LIBRARY
export TOOLS=${TOOLS:-/foss/tools} PDK_ROOT=${PDK_ROOT:-/foss/pdks}
if [ -f /etc/profile.d/iic-osic-tools-setup.sh ]; then
    # shellcheck source=/dev/null
    . /etc/profile.d/iic-osic-tools-setup.sh
fi

# Host programs in ~/.local/bin are built for the host OS: never let them
# shadow the container's tools.
PATH=$(printf '%s' "$PATH" | tr ':' '\n' | grep -vx "$HOME/.local/bin" | paste -sd: -)
export PATH="$FOSSLAB_PREFIX/libexec:$PATH"
export PYTHONPATH="$FOSSLAB_PREFIX/app${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPYCACHEPREFIX=/tmp/fosslab-pycache-$(id -u)

# KLayout: settings in the user's home, our macros first, then the PDK's.
export KLAYOUT_HOME=$HOME/.klayout
mkdir -p "$KLAYOUT_HOME" 2>/dev/null
# First run: start from the image's curated settings, showing the full
# hierarchy (otherwise KLayout asks with a modal tip at the first layout).
if [ ! -f "$KLAYOUT_HOME/klayoutrc" ] && [ -f /headless/.klayout/klayoutrc ]; then
    sed 's#</config>#  <full-hierarchy-new-cell>true</full-hierarchy-new-cell>\n  <tip-window-hidden>hide-empty-layers=0,</tip-window-hidden>\n</config>#' \
        /headless/.klayout/klayoutrc > "$KLAYOUT_HOME/klayoutrc" 2>/dev/null
fi
export KLAYOUT_PATH="$KLAYOUT_HOME:$FOSSLAB_PREFIX/share/klayout:/headless/.klayout:$PDKPATH/libs.tech/klayout:$PDKPATH/libs.tech/klayout/tech"

export EDITOR=${FOSSLAB_EDITOR:-${EDITOR:-gedit}}
export SHELL=/bin/bash

TOOL=$1
shift

case "$TOOL" in
fosslab-shell|shell)
    # An interactive shell with the whole environment, for advanced users.
    export PS1='[fosslab \W]\$ '
    exec bash --norc -i "$@"
    ;;
fosslab-env)
    env | sort
    exit 0
    ;;
esac

exec "$TOOL" "$@"
