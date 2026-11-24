#!/bin/bash
# Add students to the course (creating their accounts if needed) and give
# the teachers read access to their FOSSLab workspace.
#
#   add_students.sh students.csv          one student per line: user[,Full Name[,password]]
#   add_students.sh alice bob carol       existing accounts or new ones
#   add_students.sh --acl-only alice      only (re)apply the access rights
#
# New accounts get the password from the CSV, or a random one; random
# passwords are written to /root/fosslab_passwords.txt (root only) and must
# be changed at the first login.
#
# Access model: the teachers' group gets traverse (x) on the student's home
# and $FOSSLAB_ACL_MODE (rX = read) on ~/fosslab, inherited by new files
# (default ACLs). Nothing else in the home is readable to them.

. "$(dirname "$0")/lib.sh"
need_root
load_conf

ACL_ONLY=no
if [ "${1:-}" = "--acl-only" ]; then ACL_ONLY=yes; shift; fi
[ $# -ge 1 ] || { sed -n '2,16p' "$0"; exit 2; }

PWFILE=/root/fosslab_passwords.txt

setup_one() {
    local user=$1 name=${2:-} pass=${3:-}
    if ! id "$user" >/dev/null 2>&1; then
        [ "$ACL_ONLY" = yes ] && { warn "$user does not exist"; return; }
        info "creating account $user"
        useradd -m -c "${name:-FOSSLab student}" -G "$FOSSLAB_STUDENT_GROUP" "$user" || { warn "useradd $user failed"; return; }
        if [ -z "$pass" ]; then
            pass=$(tr -dc 'A-HJ-NP-Za-km-z2-9' < /dev/urandom | head -c 10)
            umask 077
            echo "$user $pass" >> "$PWFILE"
        fi
        echo "$user:$pass" | chpasswd
        chage -d 0 "$user"            # change the password at first login
    else
        id -nG "$user" | tr ' ' '\n' | grep -qx "$FOSSLAB_STUDENT_GROUP" \
            || usermod -aG "$FOSSLAB_STUDENT_GROUP" "$user"
    fi

    local home ws
    home=$(getent passwd "$user" | cut -d: -f6)
    ws=$home/$FOSSLAB_WS_NAME
    [ -d "$home" ] || { warn "$user has no home directory"; return; }
    if [ ! -d "$ws" ]; then
        install -d -o "$user" -g "$(id -gn "$user")" -m 750 "$ws"
    fi
    setfacl -m "g:$FOSSLAB_STAFF_GROUP:x" "$home"
    setfacl -R -m "g:$FOSSLAB_STAFF_GROUP:$FOSSLAB_ACL_MODE" "$ws"
    find "$ws" -type d -exec setfacl -d -m "g:$FOSSLAB_STAFF_GROUP:$FOSSLAB_ACL_MODE" {} +
    info "$user: workspace $ws, teachers have '$FOSSLAB_ACL_MODE'"
}

if [ $# -eq 1 ] && [ -f "$1" ]; then
    while IFS=, read -r user name pass; do
        user=$(echo "$user" | tr -d '[:space:]')
        case "$user" in ''|\#*) continue ;; esac
        setup_one "$user" "$name" "$pass"
    done < "$1"
else
    for u in "$@"; do setup_one "$u"; done
fi
[ -f "$PWFILE" ] && chmod 600 "$PWFILE" && info "new passwords: $PWFILE"
exit 0
