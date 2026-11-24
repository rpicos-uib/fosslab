#!/bin/bash
# Package the WordPress plugin: upload the zip in Plugins > Add New > Upload Plugin.
set -euo pipefail
cd "$(dirname "$0")"
version=$(sed -n 's/^ \* Version: *//p' fosslab-tutorial/fosslab-tutorial.php)
out=fosslab-tutorial-$version.zip
rm -f "$out"
python3 - "$out" <<'PY'
import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk("fosslab-tutorial"):
        for f in sorted(files):
            z.write(os.path.join(root, f))
PY
ls -l "$out"
