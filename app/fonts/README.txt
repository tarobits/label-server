Noto Sans font assets

Upstream: https://github.com/google/fonts/tree/main/ofl/notosans
Source: NotoSans[wdth,wght].ttf
License: SIL Open Font License 1.1 (see OFL.txt).

The bundled regular and bold files are static instances generated with fontTools
varLib.instancer: width 100, weights 400 and 700 respectively. They are loaded
explicitly by the renderer, with system font discovery disabled, and served by
FastAPI under /fonts for browser use. The UI's authoritative label canvas displays
the backend-rendered bitmap to avoid browser font layout differences.
