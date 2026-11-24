#!/bin/bash
# Remove FOSSLab's programs and system files. Never touches user accounts,
# homes or workspaces.
#
#   sudo ./uninstall.sh            keep the image (.sif) and /etc/fosslab.conf
#   sudo ./uninstall.sh --all      remove them too

. "$(dirname "$0")/lib.sh"
need_root
load_conf

P=${FOSSLAB_PREFIX:?}
for d in runtime libexec app share bin; do rm -rf "${P:?}/$d"; done
rm -f /etc/profile.d/fosslab.sh /etc/profile.d/fosslab.csh \
      /usr/share/applications/fosslab.desktop /usr/share/applications/fosslab-supervisor.desktop \
      /usr/share/applications/fosslab-shell.desktop
if [ "${1:-}" = "--all" ]; then
    rm -f "$FOSSLAB_IMAGE"
    rmdir "$(dirname "$FOSSLAB_IMAGE")" "$P" 2>/dev/null
    rm -f /etc/fosslab.conf /etc/sysctl.d/90-fosslab-userns.conf
fi
info "FOSSLab removed (groups, accounts and workspaces were left alone)"
