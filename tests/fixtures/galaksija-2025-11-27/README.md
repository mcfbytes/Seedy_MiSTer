`Galaksija.sta.rpt`: the TimeQuest report committed in
[MiSTer-devel/Galaksija_MiSTer](https://github.com/MiSTer-devel/Galaksija_MiSTer/blob/master/output_files/Galaksija.sta.rpt)
(MIT; Quartus 17.0.2, 5CSEBA6U23I7, 2025-11-27), with its ~650 `Info (332098)` combinational-loop detail lines
removed. It is a real MiSTer core with constraint problems: three nodes Quartus treats as clocks with no clock
assignment (`div_clk[2]`, `div_clk[3]`, `T80s:cpu|MREQ_n`), 8 combinational loops analysed as latches, and
unconstrained I/O ports. Tests add ignored-constraint warnings in the exact format Quartus prints them.
