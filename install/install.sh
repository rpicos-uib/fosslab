#!/bin/bash
# FOSSLab: install everything on a Scientific Linux 7 server (also EL8/9/10).
#
#   sudo ./install.sh                 all steps
#   sudo ./install.sh 40 50           only some steps
#
# Steps:
#   10  host packages: EPEL (archive), Apptainer, ACL, X11, X2Go + XFCE
#   20  let users run Apptainer (setuid or user namespaces)
#   30  the IIC-OSIC-TOOLS image (.sif): build it or download it
#   40  FOSSLab into $FOSSLAB_PREFIX, /etc/fosslab.conf, PATH, menu entries
#   50  course groups and teachers, students' access rights
#   60  self-test as a teacher: every tool and the full IHP flow
#
# Edit fosslab.conf (next to this script) first: teachers, groups, image.
# Then add students with ./add_students.sh.

. "$(dirname "$0")/lib.sh"
need_root
touch "$LOG"
chmod 600 "$LOG"
load_conf
info "FOSSLab install, $(date), config $FOSSLAB_CONF_USED, log $LOG"

STEPS=${*:-10 20 30 40 50 60}
for s in $STEPS; do
    script=$(ls "$INSTALL_DIR/${s}"_*.sh 2>/dev/null | head -1)
    [ -n "$script" ] || die "no step $s"
    info "=== step $(basename "$script") ==="
    FOSSLAB_CONF=$FOSSLAB_CONF_USED bash "$script" || die "step $s failed: see $LOG"
done
info "all done. Students: $INSTALL_DIR/add_students.sh students.csv"
info "Teachers: log in again (new group), then run fosslab-supervisor."
