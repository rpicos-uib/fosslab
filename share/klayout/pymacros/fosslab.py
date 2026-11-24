# $description: FOSSLab menu (cross-probing to schematics, DRC/LVS/PEX)
# $autorun
# $show-in-menu: false
#
# Loaded automatically by KLayout because FOSSLab puts this folder on
# KLAYOUT_PATH (runtime/container-env.sh). Adds a "FOSSLab" menu that works
# on the layout in the current tab, by calling the fosslab command.

import os
import subprocess

import pya

_keep = []  # actions must stay referenced or KLayout drops them


def _current():
    view = pya.LayoutView.current()
    if view is None:
        return None, None, None
    cv = pya.CellView.active()
    if not cv.is_valid() or not cv.filename():
        return view, cv, None
    return view, cv, cv.filename()


def _fosslab(args, need_saved=True):
    view, cv, path = _current()
    if path is None:
        pya.MessageBox.info("FOSSLab", "Open a layout of a FOSSLab cell first (and save it).",
                            pya.MessageBox.Ok)
        return
    if need_saved and cv.is_dirty():
        ans = pya.MessageBox.question("FOSSLab", "The layout has unsaved changes. Save it now?",
                                      pya.MessageBox.Yes + pya.MessageBox.No + pya.MessageBox.Cancel)
        if ans == pya.MessageBox.Cancel:
            return
        if ans == pya.MessageBox.Yes:
            view.save_layout(cv.index(), path, True)
    env = dict(os.environ)
    env["FOSSLAB_FROM_TOOL"] = "1"
    try:
        subprocess.Popen(["fosslab"] + args + ["--file", path], env=env,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        pya.MessageBox.critical("FOSSLab", "Could not run fosslab: %s" % e, pya.MessageBox.Ok)


def _add(menu, name, title, args, need_saved=False):
    a = pya.Action()
    a.title = title
    a.on_triggered += lambda: _fosslab(args, need_saved)
    menu.insert_item("fosslab_menu.end", name, a)
    _keep.append(a)


def _setup():
    app = pya.Application.instance()
    mw = app.main_window()
    if mw is None:                      # batch mode
        return
    menu = mw.menu()
    if menu.is_valid("fosslab_menu"):
        return
    menu.insert_menu("help_menu", "fosslab_menu", "FOSSLab")
    _add(menu, "sch", "Open schematic of this cell", ["open", "--view", "schematic"])
    _add(menu, "sym", "Open symbol of this cell", ["open", "--view", "symbol"])
    _add(menu, "reveal", "Show cell in Library Manager", ["reveal"])
    _add(menu, "hier", "Hierarchy browser (from the schematic)", ["hier", "--gui"])
    menu.insert_separator("fosslab_menu.end", "sep1")
    _add(menu, "drc", "Run DRC (IHP rules)", ["drc", "--show"], need_saved=True)
    _add(menu, "lvs", "Run LVS (layout vs schematic)", ["lvs", "--show"], need_saved=True)
    _add(menu, "pex", "Extract parasitics (PEX)", ["pex", "--show"], need_saved=True)


_setup()
