# food-picture-01 — Juicy Cheeseburger

Entry for the [make.fun](https://make.fun/bounty/food-picture-01) food-picture-01
bounty ($250 pool, top 100 share the prizes).

`main.py` (Python 3.13, standard library only) draws a juicy cheeseburger —
glossy sesame bun, ruffled lettuce, tomato, melted cheddar dripping over a
charred patty — on a dark walnut table under warm light, and writes it as a
1024×1024 PNG to `/output/entry.png`. No network, no randomness: two runs
write byte-identical files.

Run it locally:

```sh
mkdir -p out && MAKEFUN_OUTPUT_DIR=out python3 main.py
```
