#!/bin/bash
# Retake the tutorial's screenshots on this machine AND put them into the
# WordPress plugin of this git clone (the plugin zip is rebuilt).
#
#   bash tests/server_shots.sh [--live]
#
# It is `fosslab shots` (also in the Library Manager: Tools > Retake
# tutorial screenshots) plus the copy into wordpress/. Run it as a normal
# user, from the clone, with FOSSLab installed from this same clone
# (sudo bash install/install.sh 40 after a git pull).

set -u
REPO=$(cd "$(dirname "$0")/.." && pwd)
OUT=${FOSSLAB_SHOTS_DIR:-$HOME/fosslab-shots}
IMG=$REPO/wordpress/fosslab-tutorial/content/img
die() { echo "server_shots: $*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "run it as a normal user, not root"
case "$REPO/" in /home/*) ;; *) die "the clone must be under /home (the tools see /home only): $REPO" ;; esac
FOSSLAB=$(command -v fosslab || echo "$REPO/bin/fosslab")
RUN=$(command -v fosslab-run || echo "$REPO/bin/fosslab-run")
if [ -d /opt/fosslab/app ] && ! diff -rq -x __pycache__ "$REPO/app" /opt/fosslab/app >/dev/null 2>&1; then
    echo "WARNING: /opt/fosslab differs from this clone: update it first with  sudo bash install/install.sh 40"
    read -r -p "Continue anyway? [y/N] " a; [ "$a" = y ] || exit 1
fi

"$FOSSLAB" shots --out "$OUT" ${1:+"$1"} || die "the capture failed: see $OUT/shots.log"
cp "$OUT"/screenshots/*.png "$IMG"/ || die "no screenshots in $OUT/screenshots"
echo "copied $(ls "$OUT"/screenshots/*.png | wc -l) screenshots to $IMG"
"$RUN" bash "$REPO/wordpress/build_zip.sh"     # python3 from the image (SL7 has python2 only)
