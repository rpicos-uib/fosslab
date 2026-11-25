#!/bin/bash
# All FOSSLab tests, inside the image, on private Xvfb displays.
#   tests/run_all.sh            (uses FOSSLAB_RUNTIME, e.g. podman on a workstation)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
RUN="$ROOT/bin/fosslab-run"
TMP=$(mktemp -d /tmp/fosslab-tests.XXXX)
fail=0
echo "== self-test (tools + full IHP flow)"
"$RUN" bash -c "cd $TMP && python3 -m fosslab selftest --dir $TMP" || fail=1
echo "== demo workspace"
"$RUN" python3 "$HERE/make_demo_ws.py" "$TMP/demo" || fail=1
echo "== xschem and KLayout integration"
"$RUN" bash "$HERE/gui_integration.sh" "$TMP/demo" || fail=1
echo "== Library Manager, hierarchy, flows, supervisor (Tk)"
"$RUN" bash -c "
D=:\$((80 + RANDOM % 9)); Xvfb \$D -screen 0 1400x900x24 -nolisten tcp >/dev/null 2>&1 & XP=\$!
sleep 2; DISPLAY=\$D python3 $HERE/test_gui_smoke.py $TMP/demo $TMP/shots; rc=\$?
kill \$XP; rm -f /tmp/.X\${D#:}-lock /tmp/.X11-unix/X\${D#:}; exit \$rc" || fail=1
echo "== op-amp example: build, DRC, LVS, corners, Monte Carlo, Verilog-A model"
"$RUN" bash -c "
set -e
W=$TMP/opamp; python3 -m fosslab -w \$W init >/dev/null
python3 -m fosslab -w \$W example opamp --solution >/dev/null
python3 -m fosslab -w \$W drc opamp_tut opamp > \$W/drc.txt; grep -q '^DRC opamp_tut/opamp: PASS' \$W/drc.txt && echo 'PASS opamp DRC'
python3 -m fosslab -w \$W lvs opamp_tut opamp > \$W/lvs.txt; grep -q '^LVS opamp_tut/opamp: PASS' \$W/lvs.txt && echo 'PASS opamp LVS'
python3 -m fosslab -w \$W corners opamp_tut tb_opamp_ac > \$W/c.txt && grep -q '^pm ' \$W/c.txt && echo 'PASS corners (15)'
python3 -m fosslab -w \$W mc opamp_tut tb_opamp_ac -n 20 > \$W/m.txt && grep -q '^vos ' \$W/m.txt && echo 'PASS Monte Carlo (20 runs)'
python3 -m fosslab -w \$W va opamp_tut opamp > \$W/va.txt; grep -q '^VA opamp_tut/opamp: PASS' \$W/va.txt && echo 'PASS Verilog-A compile'
python3 -m fosslab -w \$W mc opamp_tut tb_opamp_ac --setup model -n 10 > \$W/v.txt && grep -q '^pm ' \$W/v.txt && echo 'PASS model Monte Carlo'
" || { echo "FAIL op-amp example"; fail=1; }

echo
[ $fail -eq 0 ] && echo "ALL TESTS PASSED ($TMP)" || echo "SOME TESTS FAILED ($TMP)"
exit $fail
