#!/bin/bash
# Step 10: host packages: EPEL, Apptainer, ACL tools, X11 forwarding, fonts,
# and (optionally) an X2Go server with an XFCE desktop for remote logins.
#
# Scientific Linux 7 is end-of-life (June 2024): EPEL 7 now lives only in
# the Fedora archive, so its repository is pointed there.

. "$(dirname "$0")/lib.sh"
need_root
load_conf

EL=$(el_version)
info "host: $(os_name) (EL$EL)"
[ -n "$EL" ] || die "this script supports Red Hat-like systems (SL7, CentOS/RHEL/Rocky/Alma)"

PM=yum
command -v dnf >/dev/null 2>&1 && PM=dnf

# --- Scientific Linux 7 repositories ---------------------------------------------
# After the end of life the SL7 tree moved to .../linux/scientific/obsolete/:
# the stock repo files give 404 for every package. Point them at the new place
# (only the files that still use the old path; a local mirror is left alone).
if grep -qi "scientific linux" /etc/redhat-release 2>/dev/null && [ "$EL" = 7 ]; then
    for repo in /etc/yum.repos.d/sl*.repo /etc/yum.repos.d/repos.repo; do
        [ -f "$repo" ] || continue
        if grep -q "scientificlinux.org/linux/scientific/[^o]" "$repo"; then
            info "pointing $repo at the SL7 archive (linux/scientific/obsolete)"
            cp -n "$repo" "$repo.fosslab-orig"
            sed -i 's#\(scientificlinux.org/linux/scientific/\)\([^o]\)#\1obsolete/\2#g' "$repo"
            # mirror lists point at dead mirrors: use the archive only
            sed -i 's|^mirrorlist=|#mirrorlist=|' "$repo"
        fi
    done
    $PM clean all >/dev/null 2>&1
fi

# --- EPEL --------------------------------------------------------------------
if ! rpm -q epel-release >/dev/null 2>&1 && ! ls /etc/yum.repos.d/epel*.repo >/dev/null 2>&1; then
    info "installing EPEL"
    if [ "$EL" = 7 ]; then
        $PM -y install epel-release || $PM -y install yum-conf-epel || \
            rpm -Uvh https://archives.fedoraproject.org/pub/archive/epel/7/x86_64/Packages/e/epel-release-7-14.noarch.rpm \
            || die "cannot install EPEL"
    else
        $PM -y install epel-release || die "cannot install EPEL"
    fi
fi

if [ "$EL" = 7 ]; then
    # EPEL 7 mirrors are gone: use the archive (keeps a backup of each file).
    for repo in /etc/yum.repos.d/epel*.repo; do
        [ -f "$repo" ] || continue
        if ! grep -q "archives.fedoraproject.org/pub/archive/epel/7" "$repo"; then
            info "pointing $repo at the EPEL 7 archive"
            cp -n "$repo" "$repo.fosslab-orig"
            sed -i -e 's|^metalink=|#metalink=|' -e 's|^mirrorlist=|#mirrorlist=|' \
                -e 's|^#\?baseurl=.*/epel/7/\(.*\)|baseurl=https://archives.fedoraproject.org/pub/archive/epel/7/\1|' \
                "$repo"
            # files without a baseurl line at all (only metalink): add one per section
            if ! grep -q '^baseurl=' "$repo"; then
                sed -i 's|^\[epel\]$|[epel]\nbaseurl=https://archives.fedoraproject.org/pub/archive/epel/7/$basearch|' "$repo"
            fi
        fi
    done
    $PM clean all >/dev/null 2>&1
fi

# --- base packages -----------------------------------------------------------
PKGS="acl git wget curl squashfs-tools xorg-x11-xauth dejavu-sans-fonts dejavu-sans-mono-fonts
      dejavu-serif-fonts xorg-x11-fonts-Type1 which"
[ "$EL" = 7 ] && PKGS="$PKGS fuse fuse-libs"
[ "$EL" != 7 ] && PKGS="$PKGS fuse3 fuse-overlayfs"
# shellcheck disable=SC2086
run_logged $PM -y install $PKGS || warn "some base packages failed to install"

# --- Apptainer ---------------------------------------------------------------
if command -v apptainer >/dev/null 2>&1; then
    info "apptainer already installed: $(apptainer --version)"
else
    info "installing Apptainer"
    if ! run_logged $PM -y install apptainer; then
        if [ -n "$FOSSLAB_APPTAINER_RPM_URL" ]; then
            run_logged $PM -y install "$FOSSLAB_APPTAINER_RPM_URL" || die "cannot install $FOSSLAB_APPTAINER_RPM_URL"
        else
            die "Apptainer is not in the repositories. Set FOSSLAB_APPTAINER_RPM_URL in fosslab.conf
     to an Apptainer RPM for EL$EL (github.com/apptainer/apptainer/releases) and run again."
        fi
    fi
fi
if [ "$FOSSLAB_APPTAINER_SUID" = yes ] && ! rpm -q apptainer-suid >/dev/null 2>&1; then
    run_logged $PM -y install apptainer-suid || warn "apptainer-suid not available; relying on user namespaces (step 20)"
fi

# Apptainer needs a recent libseccomp (seccomp_version() and friends). A
# server not updated since an early SL7 minor release has an older one, and
# apptainer then dies with "undefined symbol: seccomp_version".
run_logged $PM -y update libseccomp || warn "could not update libseccomp"
if ! apptainer --version >/dev/null 2>&1; then
    err=$(apptainer --version 2>&1 | head -1)
    lib=$(ldd "$(command -v apptainer)" 2>/dev/null | awk '/libseccomp/ {print $3}')
    die "apptainer does not run: $err
     libseccomp used: ${lib:-?} (package: $(rpm -q libseccomp))
     If that library is not /usr/lib64/libseccomp.so.2, another copy shadows the system one
     (check LD_LIBRARY_PATH and /etc/ld.so.conf.d/). Otherwise update the system: yum update"
fi
info "apptainer OK: $(apptainer --version)"

# --- remote desktop ------------------------------------------------------------
if [ "$FOSSLAB_INSTALL_X2GO" = yes ]; then
    info "installing X2Go server and XFCE (remote desktop for students)"
    run_logged $PM -y install x2goserver x2goserver-xsession || warn "X2Go not installed"
    if [ "$EL" = 7 ]; then
        run_logged $PM -y groupinstall Xfce || warn "XFCE not installed"
    else
        run_logged $PM -y groupinstall "Xfce" || run_logged $PM -y install @xfce-desktop-environment \
            || warn "XFCE not installed"
    fi
fi

# ssh -X needs X11Forwarding (the default on EL, but check)
if [ -f /etc/ssh/sshd_config ] && grep -qi '^X11Forwarding no' /etc/ssh/sshd_config; then
    warn "sshd has X11Forwarding no: students can only use X2Go, not ssh -X"
fi

info "step 10 done"
