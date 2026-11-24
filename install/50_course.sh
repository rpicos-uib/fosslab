#!/bin/bash
# Step 50: course groups, teachers, and the supervisor's read access to
# every student already in the student group.

. "$(dirname "$0")/lib.sh"
need_root
load_conf

getent group "$FOSSLAB_STUDENT_GROUP" >/dev/null || run_logged groupadd "$FOSSLAB_STUDENT_GROUP"
getent group "$FOSSLAB_STAFF_GROUP" >/dev/null || run_logged groupadd "$FOSSLAB_STAFF_GROUP"

for t in $FOSSLAB_TEACHERS; do
    if id "$t" >/dev/null 2>&1; then
        run_logged usermod -aG "$FOSSLAB_STAFF_GROUP" "$t"
    else
        warn "teacher $t does not exist (create the account, then run this step again)"
    fi
done

# Existing students: re-apply the ACLs (safe to repeat).
members=$(getent group "$FOSSLAB_STUDENT_GROUP" | cut -d: -f4 | tr ',' ' ')
for u in $members; do
    "$INSTALL_DIR/add_students.sh" --acl-only "$u"
done
info "step 50 done (students: ${members:-none yet; add them with add_students.sh})"
