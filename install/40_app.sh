#!/bin/bash
# Step 40: install FOSSLab itself into $FOSSLAB_PREFIX, the system config,
# the PATH for every login, and desktop menu entries.

. "$(dirname "$0")/lib.sh"
need_root
load_conf

P=$FOSSLAB_PREFIX
info "installing FOSSLab into $P"
mkdir -p "$P"
for d in runtime libexec app share; do
    rm -rf "${P:?}/$d.new"
    cp -a "$SRC_DIR/$d" "$P/$d.new"
    rm -rf "${P:?}/$d"
    mv "$P/$d.new" "$P/$d"
done
find "$P/app" -name __pycache__ -type d -prune -exec rm -rf {} +

mkdir -p "$P/bin"
TOOLS_LIST="fosslab fosslab-supervisor fosslab-shell fosslab-run xschem klayout ngspice magic netgen
openvaf iverilog vvp gtkwave yosys librelane openroad qucs-s xyce gaw kpex"
for t in $TOOLS_LIST; do
    ln -sfn ../runtime/fosslab-run "$P/bin/$t"
done
chmod 755 "$P/runtime/fosslab-run" "$P"/libexec/*
chmod -R a+rX "$P"

# System configuration (an existing one is kept: it may have local edits).
if [ ! -f /etc/fosslab.conf ]; then
    cp "$FOSSLAB_CONF_USED" /etc/fosslab.conf
    info "wrote /etc/fosslab.conf from $FOSSLAB_CONF_USED (edit it to change groups, image, tutorial URL...)"
elif [ "$FOSSLAB_CONF_USED" != /etc/fosslab.conf ]; then
    info "keeping the existing /etc/fosslab.conf (this run used $FOSSLAB_CONF_USED)"
fi
chmod 644 /etc/fosslab.conf

cat > /etc/profile.d/fosslab.sh <<EOF
# FOSSLab: EDA tools of the IHP SG13G2 course (xschem, klayout, ngspice, ...)
case ":\$PATH:" in *":$P/bin:"*) ;; *) PATH="$P/bin:\$PATH" ;; esac
export PATH
EOF
cat > /etc/profile.d/fosslab.csh <<EOF
if ( "\$path" !~ *$P/bin* ) set path = ( $P/bin \$path )
EOF

# Desktop menu entries (X2Go/XFCE sessions)
mkdir -p /usr/share/applications
cat > /usr/share/applications/fosslab.desktop <<EOF
[Desktop Entry]
Type=Application
Name=FOSSLab Library Manager
Comment=IHP SG13G2 design manager (xschem, KLayout, ngspice)
Exec=$P/bin/fosslab
Icon=applications-engineering
Terminal=false
Categories=Development;Electronics;
EOF
cat > /usr/share/applications/fosslab-supervisor.desktop <<EOF
[Desktop Entry]
Type=Application
Name=FOSSLab Supervisor
Comment=Browse the students' FOSSLab workspaces
Exec=$P/bin/fosslab-supervisor
Icon=system-users
Terminal=false
Categories=Development;Electronics;
EOF
cat > /usr/share/applications/fosslab-shell.desktop <<EOF
[Desktop Entry]
Type=Application
Name=FOSSLab Terminal
Comment=A terminal with every EDA tool of the course
Exec=xterm -title "FOSSLab terminal" -e $P/bin/fosslab-shell
Icon=utilities-terminal
Terminal=false
Categories=Development;Electronics;
EOF
info "step 40 done"
