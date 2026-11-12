Noto Sans font assets

Upstream: https://github.com/google/fonts/tree/main/ofl/notosans
Source: NotoSans[wdth,wght].ttf
License: SIL Open Font License 1.1 (see OFL.txt).

The bundled regular and bold files are static instances generated with fontTools
varLib.instancer: width 100, weights 400 and 700 respectively. They are loaded
explicitly by the renderer, with system font discovery disabled, and served by
FastAPI under /fonts for browser use. The UI's authoritative label canvas displays
the backend-rendered bitmap to avoid browser font layout differences.

NotoSans-Variable.ttf is bundled from google/fonts commit
2984c575fdce412ee02b2baaba67672b9a9434d8, ofl/notosans/NotoSans[wdth,wght].ttf,
under the same SIL Open Font License. Weight controls use its 100–900 range
with the width axis at its default. Existing regular/bold faces remain unchanged.
