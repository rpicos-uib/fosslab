#!/bin/bash
# Step 30: the IIC-OSIC-TOOLS image as one Apptainer file (.sif), shared by
# every user. Either built here from Docker Hub (about an hour, ~45 GB free
# during the build, ~15 GB after) or downloaded (FOSSLAB_SIF_URL) after
# building it on another machine with install/build_sif.sh.

. "$(dirname "$0")/lib.sh"
need_root
load_conf

SIF=$FOSSLAB_IMAGE
IMG_DIR=$(dirname "$SIF")
mkdir -p "$IMG_DIR"
chmod 755 "$IMG_DIR"

if [ -s "$SIF" ]; then
    info "image already there: $SIF ($(du -h "$SIF" | cut -f1))"
else
    if [ -n "$FOSSLAB_SIF_URL" ]; then
        info "downloading $FOSSLAB_SIF_URL"
        run_logged wget -c -O "$SIF.part" "$FOSSLAB_SIF_URL" || die "download failed"
        mv "$SIF.part" "$SIF"
    else
        need=45
        have=$(free_gb "$IMG_DIR")
        [ "$have" -ge "$need" ] || die "building the image needs ~${need} GB free in $IMG_DIR (have ${have} GB).
     Free space, point FOSSLAB_IMAGE to a bigger disk, or set FOSSLAB_SIF_URL."
        info "building $SIF from docker://hpretl/iic-osic-tools:$FOSSLAB_IMAGE_TAG (this takes long)"
        export APPTAINER_CACHEDIR=$IMG_DIR/cache APPTAINER_TMPDIR=$IMG_DIR/tmp
        mkdir -p "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR"
        run_logged apptainer build "$SIF.part" "docker://hpretl/iic-osic-tools:$FOSSLAB_IMAGE_TAG" \
            || die "apptainer build failed (see $LOG)"
        mv "$SIF.part" "$SIF"
        rm -rf "$APPTAINER_TMPDIR" "$APPTAINER_CACHEDIR"
    fi
fi
chmod 644 "$SIF"

info "checking the image"
apptainer exec "$SIF" bash -c 'echo "IIC-OSIC-TOOLS $IIC_OSIC_TOOLS_VERSION, PDK_ROOT=$PDK_ROOT"; ls $PDK_ROOT' \
    | tee -a "$LOG" || die "the image does not run: check step 20"
info "step 30 done"
