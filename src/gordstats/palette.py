"""
One set of chart colours for the whole site.

Every page that draws a chart was choosing its own hex codes, which is how two
pages end up almost the same blue and neither one is the blue anybody chose.
These are the values, and the reasoning behind them lives here rather than
being re-derived per page.

The categorical slots are the first three of a palette selected so that every
pair of them stays distinguishable to a colour-blind reader as well as to
everyone else. Three is the cap, not a coincidence: a fourth slot puts yellow
and orange on screen together, which fails that test in exactly the charts
where any two series can end up side by side. Past three, the answer is small
multiples or folding the tail together -- never another hue.

AQUA sits below 3:1 contrast on a light background, so any chart using it needs
the numbers available in text as well, which on this site means the table that
every chart sits beside.
"""

# Categorical: identity, assigned in this fixed order and never cycled.
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
SERIES = (BLUE, ORANGE, AQUA)

# Non-data ink. Marks that carry meaning get a hue; everything else stays grey.
INK = "#0b0b0b"          # emphasis marks, reference values
MUTED = "#94a3b8"        # baselines, reference lines, de-emphasised text
GRIDLINE = "#e2e8f0"     # grid and axis rules; must recede
CONTEXT = "#d8dee7"      # the rest of the league behind one highlighted series
