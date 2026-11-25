# FOSSLab

A library-based design environment for teaching analog IC design with free
tools and the IHP SG13G2 open PDK: a Library Manager (libraries → cells →
views) that opens each view in the right program, cross-links schematic ↔
layout ↔ hierarchy, runs simulation/DRC/LVS/PEX, and a supervisor mode to
follow every student from one window. Plus the install scripts for a
Scientific Linux 7 server and a WordPress plugin with the tutorial.

**Tutorial:** https://memristors.uib.es/index.php/education/fosslab/ (an op-amp in IHP SG13G2 from schematic to
post-layout simulation, corners and Monte Carlo, with FOSSLab).

```
fosslab/
  runtime/fosslab-run      host wrapper: runs any tool inside the IIC-OSIC-TOOLS image
  runtime/container-env.sh rebuilds the image's environment for the real user and $HOME
  bin/                     xschem, klayout, ngspice, ... fosslab: symlinks to fosslab-run
  libexec/                 commands inside the image (fosslab, fosslab-supervisor)
  app/fosslab/             the manager (Python 3 + Tk, runs inside the image)
    workspace.py           design database: fosslab.lib, libs/<lib>/<cell>/<cell>.<view>
    xschemfile.py          read xschem files; symbols from pins; schematics from netlists
    hierarchy.py           design tree, resolving symbols like xschem does
    templates.py           new views, testbenches, GDS helpers
    tools.py               launch xschem/KLayout/Magic/editor set up for the workspace + IHP
    flows.py               netlist, simulate, DRC, LVS, PEX, Verilog-A (OpenVAF)
    views.py               which view of each cell a testbench simulates (schematic,
                           extracted, Verilog-A; the place to add digital views)
    simenv.py              Simulation Environment: design variables, views,
                           outputs with specs, corners, Monte Carlo; saved in
                           <tb>.simenv.json (named setups: <tb>.<name>.simenv.json)
    examples/              the tutorial's op-amp: generator (opamp.py), layout script
                           with IHP PCells (opamp_layout.py), Verilog-A models
    gui/                   Library Manager, Simulation Environment, hierarchy browser,
                           flow window, roster
    integrations/          FOSSLab menu for xschem (Tcl), KLayout cell selection
    selftest.py            every tool and the whole flow on a real IHP inverter
  share/klayout/pymacros/  FOSSLab menu for KLayout
  install/                 SL7 install (install.sh, add_students.sh, fosslab.conf)
  wordpress/               the tutorial plugin (build_zip.sh -> upload to WordPress)
  tests/                   run_all.sh: self-test, xschem/KLayout integration, GUI smoke
```

## How it fits together

Every program runs inside one image (IIC-OSIC-TOOLS 2026.07: xschem 3.4.8RC,
KLayout 0.30.9, ngspice-46, Magic 8.3.678, OpenVAF, Netgen, the IHP PDK),
through Apptainer on the server (Podman also works, for a workstation).
`fosslab-run` starts it as the calling user, with their real home, so files
belong to the student. Settings the image keeps in its read-only `/headless`
home (KLayout config, data dirs) are moved to the user's home; the first
KLayout start gets the image's curated `klayoutrc`.

Cross-linking: the manager writes `<workspace>/.fosslab/xschemrc`
(IHP's xschemrc + the workspace libraries + `integrations/xschem_fosslab.tcl`),
which adds a FOSSLab menu to xschem and makes xschem's own Simulate use
`sim/<lib>/<cell>`. KLayout loads `share/klayout/pymacros/fosslab.py` from
`KLAYOUT_PATH`. Both menus call the `fosslab` command (`open --file X --view
layout`, `hier --gui`, `lvs --show`, ...), which talks to a running manager
over a local socket (`reveal`, `refresh`).

Supervision: teachers (group `fosslab-staff`) get read access to each
student's `~/fosslab` through ACLs (set by `add_students.sh`, kept up to date
by the wrapper at every `fosslab` start). `fosslab-supervisor` lists the
students (group `fosslab`) and opens any workspace read only; flows the
teacher runs there write to the teacher's own workspace.

## Installing on a Scientific Linux 7 server (step by step)

You need: the `fosslab/` folder on the server, a sudoer account, internet
access (yum repositories and Docker Hub) and about 45 GB of free disk
during the image build (15 GB afterwards). It also works on EL8/9/10.

### 0. Before you start

Each user's design workspace will be `~/fosslab`, so the install folder
must **not** be `~/fosslab`. Move it, e.g.:

```bash
mv ~/fosslab ~/fosslab-src
cd ~/fosslab-src            # every command below runs from here
df -h /opt                  # room for the image?
```

### 1. Edit the configuration

```bash
vi install/fosslab.conf
```

| Line | What to put |
|---|---|
| `FOSSLAB_TEACHERS="rodrigo"` | your user name (and other teachers', space separated) |
| `FOSSLAB_IMAGE=/opt/fosslab/images/...sif` | a disk with room if `/opt` is small, e.g. `/data/fosslab/iic-osic-tools_2026.07.sif` |
| `FOSSLAB_TUTORIAL_URL=` | the tutorial page (default: https://memristors.uib.es/index.php/education/fosslab/) |
| `FOSSLAB_INSTALL_X2GO=yes` | `no` if students only use `ssh -X` |

### 2. System packages and permissions (about 10 min)

```bash
sudo bash install/install.sh 10 20
```

SL7 and EPEL 7 are end-of-life and their normal repositories give 404: the
script points them at the archives (`ftp.scientificlinux.org/.../obsolete/`,
`archives.fedoraproject.org`) and keeps the originals as `*.repo.fosslab-orig`.
It installs Apptainer + apptainer-suid, ACL tools, fonts, xauth, X2Go and XFCE.

If the output warns about `namespace.unpriv_enable=1` (only matters when
apptainer-suid could not be installed):

```bash
sudo grubby --update-kernel=ALL --args=namespace.unpriv_enable=1
sudo reboot
```

### 3. The tool image (about 1 hour)

Run it inside `screen` so a dropped connection does not stop it
(`screen -S FOSS`; detach `Ctrl-a d`, reattach `screen -r FOSS`):

```bash
sudo bash install/install.sh 30
```

It downloads IIC-OSIC-TOOLS 2026.07 (all the EDA tools + the IHP SG13G2 PDK)
and turns it into one `.sif` file, then runs a command inside it to prove
Apptainer works.

Not enough space or bandwidth on the server? Build the image on any machine
with Apptainer (e.g. Rocky: `sudo dnf install epel-release apptainer`) and copy it:

```bash
install/build_sif.sh 2026.07
scp iic-osic-tools_2026.07.sif server:/opt/fosslab/images/
```

then run step 30 on the server anyway (it finds the file and only checks it).

### 4. FOSSLab, groups and teachers

```bash
sudo bash install/install.sh 40 50
```

Step 40 installs FOSSLab into `/opt/fosslab`, `/etc/fosslab.conf`, the
system-wide PATH and the desktop menu entries. Step 50 creates the groups
`fosslab` (students) and `fosslab-staff` (teachers) and adds you to the latter.

**Log out and log in again** (new group, new PATH).

### 5. Check everything works (about 1 minute)

As yourself, without sudo:

```bash
bash install/60_check.sh
```

Every line must say `[PASS]`, ending with `ALL PASSED`: every tool, and the
full IHP flow on an inverter (simulation, DRC, LVS, PEX, post-layout simulation).

### 6. Add the students

```bash
cp install/students.csv.example students.csv
vi students.csv            # one per line:  user,Full Name[,initial password]
sudo bash install/add_students.sh students.csv
```

Missing accounts are created; without a password in the CSV they get a random
one (listed in `/root/fosslab_passwords.txt`) to be changed at first login.
Existing accounts are just added to the `fosslab` group. Every student gets
`~/fosslab`, readable (not writable) by `fosslab-staff`. One more later:
`sudo bash install/add_students.sh alice`.

### 7. Use it

- Students connect with X2Go (session type XFCE) or `ssh -X`, and run
  `fosslab` (or *Development > FOSSLab Library Manager*).
- You: `fosslab` (your workspace), `fosslab-supervisor` (Student selector +
  Roster), `fosslab example opamp` (the tutorial's reference library).
- Reference library for the students, read only: each student adds
  `INCLUDE /home/<you>/fosslab/fosslab.lib` to `~/fosslab/fosslab.lib`
  (your workspace must be readable by group `fosslab`).
- Look: *Tools > Interface > New / Classical* switches every open window at
  once and is remembered per user (`~/.config/fosslab/gui.json`);
  `FOSSLAB_UI=new|classic` overrides it.

### If something fails

- Everything is logged in `/var/log/fosslab-install.log`; any step can be
  re-run alone, e.g. `sudo bash install/install.sh 40`.
- `apptainer exec` fails with a user-namespace error: see step 2.
- No windows appear: `echo $DISPLAY` must be set (X2Go or `ssh -X`).
- `sudo bash install/uninstall.sh` removes FOSSLab (never accounts or workspaces).

## Develop / test on a workstation with Podman

```
export FOSSLAB_RUNTIME=podman FOSSLAB_CONF=/nonexistent
bin/fosslab                       # the Library Manager on ~/fosslab
bin/fosslab selftest
tests/run_all.sh                  # everything, on private Xvfb displays
```

## The tutorial's example

`fosslab example opamp` writes the reference library `opamp_tut`: a two-stage
Miller op-amp in IHP SG13G2 (A0 57.6 dB, UGF 16.2 MHz, PM 60.4 deg, 91 uW),
its DRC/LVS-clean layout drawn from IHP PCells, testbenches with their
Simulation Environment setups (15 corners, Monte Carlo), and a Verilog-A
view of the op-amp with the setup `model` of `tb_opamp_ac` that simulates it
instead of the transistors (`--solution` adds the exercise's two-pole view
`opamp_2pole.va` and its setup `model_2pole`).

### Retaking the tutorial's screenshots

On the machine where FOSSLab is installed (e.g. the course server), as a
normal user: in the Library Manager, *Tools > Retake tutorial screenshots...*,
or `fosslab shots [--out ~/fosslab-shots] [--live]`. It rebuilds the op-amp
from scratch in that folder (never in `~/fosslab`), runs every flow, takes
every screenshot from the real programs (`<out>/screenshots/`) and lists every
number the chapters quote next to this machine's value (about 10 minutes).
By default it uses a private virtual display; `--live` uses yours (the
pictures then show your X2Go desktop; do not touch the mouse meanwhile).

To put the new pictures straight into the plugin of a git clone and rebuild
its zip: `bash tests/server_shots.sh [--live]` from the clone.

## Tested

- On this workstation (Rocky 10, Podman, image 2026.07): `tests/run_all.sh`
  passes: 8 tools, the full flow on a real IHP inverter (schematic, symbol,
  testbench, simulation, DRC, LVS, PEX, post-layout simulation), the xschem
  and KLayout menus, the Tk windows and the supervisor, and the op-amp
  example (DRC, LVS, corners, Monte Carlo, Verilog-A model and its Monte Carlo).
- On a Scientific Linux 7.9 container (bash 4.2, yum): install steps 10, 20, 40, 50
  and `add_students.sh` (SL7 and EPEL 7 repositories repointed to their
  archives; Apptainer 1.3.2 + apptainer-suid, X2Go, XFCE installed; ACLs give
  teachers read-only access), and the Apptainer branch of `fosslab-run` with a
  small stand-in image (user, home, working dir, DISPLAY, binds, inherited ACLs).
- Not tested here: the real 15 GB image under Apptainer on SL7's 3.10 kernel
  (step 30) and step 60. Run `install.sh 30 60` on the server; step 60 is
  the self-test above.

## License

Copyright 2026 R. Picos (Universitat de les Illes Balears).

Licensed under the Apache License, Version 2.0: see [LICENSE](LICENSE).
The tools FOSSLab runs (xschem, ngspice, KLayout, Magic, OpenVAF, ...), the
IIC-OSIC-TOOLS image and the IHP SG13G2 PDK keep their own licenses.
