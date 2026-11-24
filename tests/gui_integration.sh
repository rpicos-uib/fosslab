#!/bin/bash
# GUI integration test: KLayout macro menu + xschem FOSSLab menu, on a private
# Xvfb display (nothing shows on the real screen). Run inside the image:
#     fosslab-run bash tests/gui_integration.sh WORKSPACE_WITH_DEMO
# (build one with tests/make_demo_ws.py)
set -u
WS=$1
HERE=$(cd "$(dirname "$0")" && pwd)
DISP=:$((90 + RANDOM % 9))
Xvfb "$DISP" -screen 0 1400x900x24 -nolisten tcp >/dev/null 2>&1 &
XP=$!
trap 'kill -9 $XP 2>/dev/null; rm -f /tmp/.X${DISP#:}-lock /tmp/.X11-unix/X${DISP#:}' EXIT
sleep 2
export DISPLAY=$DISP
cd "$WS"

# KLayout: the menu exists and lists our entries; the layout and cell loaded.
cat > /tmp/fosslab_kl_check_$$.py <<'PY'
import pya
m = pya.Application.instance().main_window().menu()
print("KL_MENU", m.is_valid("fosslab_menu"))
print("KL_ITEMS", "|".join(m.action(i).title for i in m.items("fosslab_menu") if m.action(i).title))
cv = pya.CellView.active()
print("KL_CELL", cv.cell_name)
print("KL_TECH", cv.technology)
PY
KL=$(timeout -k 2 60 klayout -e -n sg13g2 libs/work/inv/inv.gds -r /tmp/fosslab_kl_check_$$.py 2>&1 | grep '^KL_')
rm -f /tmp/fosslab_kl_check_$$.py
echo "$KL"

# xschem: FOSSLab menu, per-cell simulation folder, cell lookup.
timeout -k 2 60 xschem --rcfile .fosslab/xschemrc --command '
after 2000 {
  set m [xschem get top_path].menubar.fosslab
  puts "XS_MENU=[winfo exists $m]"
  set items {}
  for {set i 0} {$i <= [$m index end]} {incr i} {
    if {[$m type $i] eq "command"} { lappend items [$m entrycget $i -label] }
  }
  puts "XS_ITEMS=[join $items |]"
  puts "XS_LOC=[fosslab_locate [xschem get schname]]"
  set_netlist_dir 0
  puts "XS_NETLIST_DIR=$netlist_dir"
  xschem exit closewindow force
}' libs/work/tb_inv/tb_inv.sch 2>&1 | grep '^XS_' > /tmp/fosslab_xs_$$.out
XS=$(cat /tmp/fosslab_xs_$$.out); rm -f /tmp/fosslab_xs_$$.out
echo "$XS"

fail=0
check() { if echo "$1" | grep -q -- "$2"; then echo "PASS $3"; else echo "FAIL $3"; fail=1; fi; }
check "$KL" "KL_MENU True" "KLayout FOSSLab menu"
check "$KL" "KL_TECH sg13g2" "KLayout loads the sg13g2 technology"
check "$KL" "KL_CELL inv" "KLayout shows the cell"
check "$XS" "XS_MENU=1" "xschem FOSSLab menu"
check "$XS" "XS_LOC=work tb_inv" "xschem knows the cell of the schematic"
check "$XS" "XS_NETLIST_DIR=.*/sim/work/tb_inv" "xschem simulates in the per-cell folder"
exit $fail
