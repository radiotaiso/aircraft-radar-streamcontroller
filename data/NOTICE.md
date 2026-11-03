# Map outline data

`map.json` is derived from [Natural Earth](https://www.naturalearthdata.com)
1:10m vector data (coastline, lakes, admin-1 state/province lines, urban areas)
for the whole world, simplified to 0.02 degrees and stored as flat coordinate
arrays by `scripts/build_map.py`.

Natural Earth is in the public domain; no attribution is required. See
https://www.naturalearthdata.com/about/terms-of-use/.

Regenerate for another region:

    python3 scripts/build_map.py --bbox W S E N
