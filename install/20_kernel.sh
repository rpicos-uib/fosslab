#!/bin/bash
# Step 20: let Apptainer run containers as normal users.
#
# With apptainer-suid (step 10) this already works on EL7. Without it,
# Apptainer needs unprivileged user namespaces, which EL7 ships disabled
# (user.max_user_namespaces = 0).

. "$(dirname "$0")/lib.sh"
need_root
load_conf

if rpm -q apptainer-suid >/dev/null 2>&1; then
    info "apptainer-suid installed: setuid mode, no kernel change needed"
else
    cur=$(sysctl -n user.max_user_namespaces 2>/dev/null || echo "")
    if [ -z "$cur" ]; then
        warn "this kernel has no user.max_user_namespaces: install apptainer-suid"
    elif [ "$cur" -lt 1000 ]; then
        info "enabling user namespaces (was $cur)"
        echo "user.max_user_namespaces = 15000" > /etc/sysctl.d/90-fosslab-userns.conf
        sysctl -p /etc/sysctl.d/90-fosslab-userns.conf || die "sysctl failed"
    else
        info "user namespaces already enabled ($cur)"
    fi
fi

# EL7 3.10 kernels: user namespaces need namespace.unpriv_enable=1 on some
# builds; tell the admin instead of editing the boot line.
if [ "$(el_version)" = 7 ] && ! rpm -q apptainer-suid >/dev/null 2>&1; then
    if ! grep -q "namespace.unpriv_enable=1" /proc/cmdline; then
        warn "if 'apptainer exec' fails with 'user namespaces not enabled', add
     namespace.unpriv_enable=1 to the kernel command line (grubby --update-kernel=ALL
     --args=namespace.unpriv_enable=1) and reboot, or install apptainer-suid."
    fi
fi
info "step 20 done"
