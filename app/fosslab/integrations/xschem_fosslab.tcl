# FOSSLab integration for xschem.
#
# Sourced through tcl_files by the xschemrc that FOSSLab generates
# (<workspace>/.fosslab/xschemrc), which also defines:
#   fosslab_libs     list of {name dir} pairs of the workspace libraries
#   fosslab_runroot  where sim/ and verif/ live
#
# Adds a "FOSSLab" menu (cross-probing to layout, hierarchy browser,
# Library Manager, DRC/LVS/PEX) and makes xschem's own Netlist/Simulate
# buttons use the per-cell folder <runroot>/sim/<lib>/<cell>.

# Which workspace cell does a file belong to? Returns {lib cell} or {}.
proc fosslab_locate {path} {
  global fosslab_libs
  if {![info exists fosslab_libs]} { return {} }
  set path [file normalize $path]
  foreach pair $fosslab_libs {
    lassign $pair name dir
    set dir [file normalize $dir]
    if {[string first "$dir/" $path] == 0} {
      set rest [string range $path [expr {[string length $dir] + 1}] end]
      return [list $name [lindex [file split $rest] 0]]
    }
  }
  return {}
}

# The simulation folder of the current schematic's cell: where FOSSLab and
# xschem's own Simulate write the .raw files. Graphs use it, e.g.
#   rawfile=[fosslab_simdir]/tb_opamp_ac.raw  autoload=1
proc fosslab_simdir {} {
  global fosslab_runroot netlist_dir
  set loc [fosslab_locate [xschem get schname]]
  if {$loc ne {} && [info exists fosslab_runroot]} {
    return [file join $fosslab_runroot sim [lindex $loc 0] [lindex $loc 1]]
  }
  return $netlist_dir
}

# Per-cell simulation folder, unless the user chose another
# netlist-dir mode in Simulation > Set netlist dir.
if {[info procs simuldir] ne {} && [info procs fosslab_orig_simuldir] eq {}} {
  rename simuldir fosslab_orig_simuldir
  proc simuldir {} {
    global netlist_dir local_netlist_dir fosslab_runroot
    # Batch flows (FOSSLAB_BATCH) choose their own folder with -o.
    if {$local_netlist_dir == 0 && [info exists fosslab_runroot]
        && ![info exists ::env(FOSSLAB_BATCH)]} {
      set loc [fosslab_locate [xschem get schname]]
      if {$loc ne {}} {
        set netlist_dir [file join $fosslab_runroot sim [lindex $loc 0] [lindex $loc 1]]
        return $netlist_dir
      }
    }
    return [fosslab_orig_simuldir]
  }
}

# Run a fosslab command in the background; errors go to a message box.
proc fosslab_run {args} {
  if {[catch {exec fosslab {*}$args >@ stdout 2>@ stderr &} err]} {
    tk_messageBox -icon error -title FOSSLab -message "fosslab $args\n\n$err"
  }
}

proc fosslab_current {} {
  set f [xschem get schname]
  if {[file extension $f] ni {.sch .sym}} {
    tk_messageBox -icon warning -title FOSSLab -message "Save the schematic first."
    return {}
  }
  return $f
}

# Absolute path of the symbol of the (first) selected instance.
proc fosslab_selected_symbol {} {
  set sel [xschem selected_set]
  if {[llength $sel] == 0} {
    tk_messageBox -icon info -title FOSSLab -message "Select an instance first."
    return {}
  }
  set inst [lindex $sel 0]
  set sym [xschem getprop instance $inst cell::name]
  return [abs_sym_path $sym]
}

proc fosslab_with_current {args} {
  set f [fosslab_current]
  if {$f ne {}} { fosslab_run {*}$args --file $f }
}

proc fosslab_with_selected {args} {
  set s [fosslab_selected_symbol]
  if {$s ne {}} { fosslab_run {*}$args --file $s }
}

proc fosslab_menu {} {
  global has_x
  if {![info exists has_x]} { return }
  set topwin [xschem get top_path]
  set m $topwin.menubar.fosslab
  if {[winfo exists $m]} { return }
  if {[catch {$topwin.menubar insert Netlist cascade -label FOSSLab -menu $m}]} {
    $topwin.menubar add cascade -label FOSSLab -menu $m
  }
  menu $m -tearoff 0

  $m add command -label "Show cell in Library Manager" \
      -command {fosslab_with_current reveal}
  $m add command -label "Hierarchy browser" \
      -command {fosslab_with_current hier --gui}
  $m add separator
  $m add command -label "Open layout of this cell" \
      -command {fosslab_with_current open --view layout}
  $m add command -label "Open layout of selected instance" \
      -command {fosslab_with_selected open --view layout}
  $m add command -label "Open schematic of selected instance (new tab)" \
      -command {fosslab_with_selected open --view schematic}
  $m add command -label "Open Verilog-A of selected instance" \
      -command {fosslab_with_selected open --view veriloga}
  $m add separator
  $m add command -label "Create/update symbol from pins" \
      -command {fosslab_with_current symbol}
  $m add command -label "Create testbench for this cell" \
      -command {fosslab_with_current testbench --open}
  $m add separator
  $m add command -label "Simulate (batch, with log)" \
      -command {fosslab_with_current sim --show}
  $m add command -label "Simulation Environment (corners, Monte Carlo)..." \
      -command {fosslab_with_current simenv}
  $m add command -label "Run DRC on this cell's layout" \
      -command {fosslab_with_current drc --show}
  $m add command -label "Run LVS (layout vs this schematic)" \
      -command {fosslab_with_current lvs --show}
  $m add command -label "Extract parasitics (PEX)" \
      -command {fosslab_with_current pex --show}
  $m add separator
  $m add command -label "Help: hierarchy keys" -command {
    tk_messageBox -title "FOSSLab: moving in the hierarchy" -message \
"e        descend into the selected instance's schematic
i        descend into its symbol
Ctrl+e   go back up one level
FOSSLab > Hierarchy browser   the whole tree at once"
  }
}

append postinit_commands "fosslab_menu\n"
