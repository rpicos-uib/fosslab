#!/bin/bash
# Step 60: prove the installation works, as a normal user: every tool, and
# the whole flow (schematic, simulation, DRC, LVS, PEX, post-layout
# simulation) on a real IHP SG13G2 inverter. Takes about a minute.
#
#   60_check.sh [USER]      (default: the first teacher)

. "$(dirname "$0")/lib.sh"
load_conf

user=${1:-$(echo "$FOSSLAB_TEACHERS" | awk '{print $1}')}
cmd="$FOSSLAB_PREFIX/bin/fosslab selftest"
if [ "$(id -u)" -eq 0 ]; then
    [ -n "$user" ] && id "$user" >/dev/null 2>&1 || die "give a normal user to run the check as"
    info "running the self-test as $user"
    # a login shell, so the user's own environment is used
    su - "$user" -c "cd /tmp && $cmd" 2>&1 | tee -a "$LOG"
    rc=${PIPESTATUS[0]}
else
    (cd /tmp && $cmd)
    rc=$?
fi
[ "$rc" -eq 0 ] && info "FOSSLab is ready." || die "self-test failed (rc=$rc)"
