# seedy_sta.tcl: per-seed timing data for MiSTer Seedy.
# Usage: quartus_sta -t seedy_sta.tcl <project> <revision> <out.tsv> <npaths> [watch-file]
#   watch-file: one register glob per line (e.g. *ramimg*); blank lines and # comments ignored
# Writes tab-separated records; Python (seedy/parse.py) does all interpretation:
#   corner  <cond>
#   clock   <cond> <kind> <clock> <slack> <tns>            kind = setup|hold|recovery|removal
#   fmax    <cond> <clock> <fmax_mhz> <restricted_mhz>
#   path    <cond> <kind> <slack> <from> <to> <launch> <latch>
#   watch   <glob> <dir> <cond> <kind> <slack> <from> <to> <launch> <latch>   dir = from|to
#   nowatch <glob>                                         no register matched the glob
set project  [lindex $quartus(args) 0]
set revision [lindex $quartus(args) 1]
set outfile  [lindex $quartus(args) 2]
set npaths   [lindex $quartus(args) 3]
set globs    {}
if {[llength $quartus(args)] > 4 && [file exists [lindex $quartus(args) 4]]} {
  set wf [open [lindex $quartus(args) 4] r]
  foreach line [split [read $wf] "\n"] {
    set line [string trim $line]
    if {$line ne "" && [string index $line 0] ne "#"} { lappend globs $line }
  }
  close $wf
}

proc clk_name {c} {
  if {$c eq ""} { return "" }
  return [get_clock_info -name $c]
}
proc path_fields {p} {
  set from [get_node_info -name [get_path_info $p -from]]
  set to   [get_node_info -name [get_path_info $p -to]]
  return [join [list [format %.3f [get_path_info $p -slack]] $from $to \
                [clk_name [get_path_info $p -from_clock]] [clk_name [get_path_info $p -to_clock]]] "\t"]
}

project_open $project -revision $revision
create_timing_netlist
read_sdc
update_timing_netlist
set f [open $outfile w]
set matched {}
foreach g $globs {
  set regs [get_registers -nowarn $g]
  if {[get_collection_size $regs] == 0} { puts $f "nowatch\t$g" } else { lappend matched $g }
}
foreach cond [get_available_operating_conditions] {
  set_operating_conditions $cond
  update_timing_netlist
  puts $f "corner\t$cond"
  foreach kind {setup hold recovery removal} {
    foreach d [get_clock_domain_info -$kind] {
      # {clock slack keeper_tns edge_tns}
      puts $f [join [list clock $cond $kind [lindex $d 0] [lindex $d 1] [lindex $d 2]] "\t"]
    }
  }
  foreach d [get_clock_fmax_info] {
    puts $f [join [list fmax $cond [lindex $d 0] [lindex $d 1] [lindex $d 2]] "\t"]
  }
  foreach kind {setup hold} {
    foreach_in_collection p [get_timing_paths -$kind -npaths $npaths] {
      puts $f "path\t$cond\t$kind\t[path_fields $p]"
    }
    foreach g $matched {
      set regs [get_registers -nowarn $g]
      foreach dir {from to} {
        foreach_in_collection p [get_timing_paths -$kind -npaths 10 -$dir $regs] {
          puts $f "watch\t$g\t$dir\t$cond\t$kind\t[path_fields $p]"
        }
      }
    }
  }
}
close $f
delete_timing_netlist
project_close
