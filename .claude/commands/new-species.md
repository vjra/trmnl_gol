---
description: Search for new Lenia species and add the good ones to the rotation
argument-hint: [seed] [name-prefix]
---

Find new species and let me choose which join the display rotation.

1. Run `python lenia_trmnl.py search --soup 300 --n 1500 --seed ${1:-$RANDOM} --prefix ${2:-New} --out /tmp/new_species.json`.
2. `python lenia_trmnl.py overview --species /tmp/new_species.json --reference --out /tmp/new_overview.png`,
   `python lenia_trmnl.py gifs --species /tmp/new_species.json --outdir /tmp/new_gifs --scale 6 --count 1 --follow`
   and `... gifs --outdir /tmp/new_eco --scale 3 --count 4`. Show me the overview and a still per GIF. Describe each briefly (moves? pulses? replicates? how it looks on 1-bit).
3. Append all of them to species_all.json. Ask which join the rotation and merge those into species.json (unique names, keep existing ones unless I say otherwise).
4. `pytest -q`, regenerate docs/examples, commit with a message listing the added species.
