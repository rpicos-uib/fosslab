#!/bin/bash
# Test install/fosslab-course as root, on throwaway containers of an old and
# a new Linux (it creates users and groups, so never on a real server):
#
#   bash tests/test_courses.sh                 CentOS 7 (as SL7), Rocky 9, Ubuntu 24.04
#   bash tests/test_courses.sh IMAGE...        other images
#
# Inside, the tool image is replaced by a stub of fosslab-run that writes a
# fake example library, so only the course logic is tested.

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")

if [ "${1:-}" != --inside ]; then
    images=("$@")
    [ ${#images[@]} -gt 0 ] || images=(docker.io/library/centos:7 docker.io/library/rockylinux:9
                                       docker.io/library/ubuntu:24.04)
    fail=0
    for img in "${images[@]}"; do
        echo "=== $img"
        podman run --rm --security-opt label=disable -v "$ROOT:/src:ro" "$img" bash /src/tests/test_courses.sh --inside || fail=1
    done
    [ $fail -eq 0 ] && echo "ALL COURSE TESTS PASSED" || echo "SOME COURSE TESTS FAILED"
    exit $fail
fi

# ---------------------------------------------------------------- inside the container
set -u
if ! command -v setfacl >/dev/null; then
    { command -v dnf && dnf -q -y install acl; } >/dev/null 2>&1 \
        || { apt-get -qq update && apt-get -qq -y install acl; } >/dev/null 2>&1
fi
bash --version | head -1
P=/opt/fl
mkdir -p $P/bin
cp -a /src/install $P/install
cat > $P/bin/fosslab-run <<'EOF'
#!/bin/bash
# stub: fosslab -w DIR init | fosslab -w DIR example opamp --lib LIB
shift; [ "$1" = -w ] || exit 1; dir=$2; shift 2
case "$1" in
    init) mkdir -p "$dir/libs/work"; printf 'DEFINE work libs/work\n' > "$dir/fosslab.lib" ;;
    example) lib=$4; mkdir -p "$dir/libs/$lib/opamp"; echo sch > "$dir/libs/$lib/opamp/opamp.sch"
             echo "DEFINE $lib libs/$lib" >> "$dir/fosslab.lib" ;;
esac
EOF
chmod 755 $P/bin/fosslab-run
cat > /etc/fosslab.conf <<EOF
FOSSLAB_PREFIX=$P
FOSSLAB_STAFF_GROUP=fosslab-staff
FOSSLAB_STUDENT_GROUP=fosslab
FOSSLAB_WS_NAME=fosslab
FOSSLAB_TEACHERS="tina"
FOSSLAB_ACL_MODE=rX
EOF
export FOSSLAB_INSTALL_LOG=/tmp/install.log
FC=$P/install/fosslab-course
ok=0; bad=0
check() {   # check "what" command...
    if "${@:2}" >/dev/null 2>&1; then echo "PASS $1"; ok=$((ok + 1)); else echo "FAIL $1"; bad=$((bad + 1)); fi
}
has_acl() { getfacl -p "$1" 2>/dev/null | grep -q "^$2"; }

groupadd fosslab-staff; groupadd fosslab
useradd -m tina; usermod -aG fosslab-staff tina      # teacher
useradd -m tom                                       # a teacher not in the staff group
useradd -m -c "Ann Old" ann; usermod -aG fosslab ann # existing student (legacy group)
mkdir -p /home/ann/fosslab; echo "DEFINE work libs/work" > /home/ann/fosslab/fosslab.lib
chown -R ann: /home/ann/fosslab

cat > /tmp/c1.course <<'EOF'
format   1
id       micro-2026
title    Microelectronics 2026
state    active
teacher  tina
access   rX
example  ro
library  opamp_tut
student  ann   Ann Old
student  bob   Bob New
EOF

# who may apply
SUDO_USER=tom $FC apply /tmp/c1.course >/dev/null 2>&1
check "a teacher outside the staff group cannot create a course" test ! -f $P/courses/micro-2026.course
SUDO_USER=tina $FC apply /tmp/c1.course > /tmp/out1 2>&1
check "the staff teacher creates it" test -f $P/courses/micro-2026.course
check "course file readable by its teachers only" bash -c "stat -c '%a %G' $P/courses/micro-2026.course | grep -qx '640 fl-micro-2026-t'"
check "groups: students" bash -c "[ \"\$(getent group fl-micro-2026 | cut -d: -f4)\" = ann,bob ]"
check "groups: teachers" bash -c "[ \"\$(getent group fl-micro-2026-t | cut -d: -f4)\" = tina ]"
check "new account bob created" id bob
check "existing account ann kept" bash -c "getent passwd ann | grep -q 'Ann Old'"
check "first password of bob listed" grep -q '^bob ' $P/courses/micro-2026.passwords
check "password file private" bash -c "stat -c '%a' $P/courses/micro-2026.passwords | grep -qx 640"
check "workspaces ~/fosslab-micro-2026" test -f /home/bob/fosslab-micro-2026/fosslab.lib -a -f /home/ann/fosslab-micro-2026/fosslab.lib
check "workspace owned by the student" bash -c "stat -c %U /home/bob/fosslab-micro-2026 | grep -qx bob"
check "legacy ~/fosslab untouched" bash -c "[ \"\$(cat /home/ann/fosslab/fosslab.lib)\" = 'DEFINE work libs/work' ]"
check "teachers: rX on the workspace" has_acl /home/bob/fosslab-micro-2026 "group:fl-micro-2026-t:r-x"
check "teachers: default ACL for new files" has_acl /home/bob/fosslab-micro-2026 "default:group:fl-micro-2026-t:r-x"
check "teachers: only traverse on the home" has_acl /home/bob "group:fl-micro-2026-t:--x"
check "shared example built" test -f $P/shared/micro-2026/libs/opamp_tut/opamp/opamp.sch
check "shared example: no 'work' library" bash -c "! grep -q 'DEFINE work' $P/shared/micro-2026/fosslab.lib"
check "students include it read only" grep -qx "INCLUDE $P/shared/micro-2026/fosslab.lib" /home/bob/fosslab-micro-2026/fosslab.lib
check "shared copy readable by the course only" bash -c "stat -c '%a %G' $P/shared/micro-2026 | grep -qx '750 fl-micro-2026'"
check "public index" grep -q '^micro-2026 active rX Microelectronics 2026' $P/courses/index
check "list as teacher shows the course" bash -c "su tina -s /bin/bash -c '$FC list' | grep -q micro-2026"
check "list as another user hides it" bash -c "! su tom -s /bin/bash -c '$FC list' | grep -q micro-2026"

# second version: ann leaves, carl joins, own copies, read+write
sed -e '/^student  ann/d' -e 's/^example  ro/example  rw/' -e 's/^access   rX/access   rwX/' /tmp/c1.course > /tmp/c2.course
echo "student  carl  Carl Third" >> /tmp/c2.course
SUDO_USER=tom $FC apply /tmp/c2.course >/dev/null 2>&1
check "a non-teacher cannot change it" bash -c "[ \"\$(getent group fl-micro-2026 | cut -d: -f4)\" = ann,bob ]"
SUDO_USER=tina $FC apply /tmp/c2.course > /tmp/out2 2>&1
check "students now bob,carl" bash -c "[ \"\$(getent group fl-micro-2026 | cut -d: -f4)\" = bob,carl ]"
check "ann: teachers' access removed" bash -c "! getfacl -p /home/ann/fosslab-micro-2026 2>/dev/null | grep -q fl-micro-2026-t"
check "ann: account and work kept" test -f /home/ann/fosslab-micro-2026/fosslab.lib
check "rw: own copy in the workspace" test -f /home/carl/fosslab-micro-2026/libs/opamp_tut/opamp/opamp.sch
check "rw: own copy owned by the student" bash -c "stat -c %U /home/carl/fosslab-micro-2026/libs/opamp_tut | grep -qx carl"
check "rw: shared INCLUDE replaced by DEFINE" bash -c "f=/home/bob/fosslab-micro-2026/fosslab.lib; ! grep -q '^INCLUDE' \$f && grep -q '^DEFINE opamp_tut libs/opamp_tut' \$f"
check "access now rwX" has_acl /home/bob/fosslab-micro-2026 "group:fl-micro-2026-t:rwx"
check "applying twice changes nothing" bash -c "SUDO_USER=tina $FC apply /tmp/c2.course >/dev/null 2>&1 && [ \"\$(grep -c '^DEFINE opamp_tut' /home/bob/fosslab-micro-2026/fosslab.lib)\" = 1 ]"

# a file from a newer FOSSLab is refused
sed 's/^format   1/format   9/' /tmp/c2.course > /tmp/c9.course
check "newer course format refused" bash -c "! SUDO_USER=tina $FC apply /tmp/c9.course"
sed 's/^id       micro-2026/id       Bad Id/' /tmp/c2.course > /tmp/cbad.course
check "invalid id refused" bash -c "! $FC apply /tmp/cbad.course"

# archive, legacy import
SUDO_USER=tina $FC archive micro-2026 >/dev/null 2>&1
check "archive" grep -q '^micro-2026 archived' $P/courses/index
$FC import-legacy > /tmp/out3 2>&1
check "legacy import: course default with ann" bash -c "grep -q '^student  ann' $P/courses/default.course"
check "legacy: workspace stays ~/fosslab" has_acl /home/ann/fosslab "group:fl-default-t:r-x"
check "legacy: teacher from FOSSLAB_TEACHERS" bash -c "[ \"\$(getent group fl-default-t | cut -d: -f4)\" = tina ]"

echo "$ok passed, $bad failed"
[ $bad -eq 0 ] || { echo "--- output of the first apply:"; cat /tmp/out1; echo "--- log:"; tail -30 /tmp/install.log; }
[ $bad -eq 0 ]
