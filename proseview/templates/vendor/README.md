# Vendored front-end dependencies

These files are checked in so the dashboard works offline and so
upstream major releases can't break the page silently. They're served
by the proseview server at `/vendor/<file>`.

| File                          | Source                                    | Pinned version |
|-------------------------------|-------------------------------------------|----------------|
| chart.js                      | npm:chart.js                              | 4.5.0          |
| chartjs-plugin-annotation.js  | npm:chartjs-plugin-annotation             | 3.0.1          |
| marked.js                     | npm:marked                                | 14.1.4         |
| pdfjs/pdf.min.mjs, pdfjs/pdf.worker.min.mjs | npm:pdfjs-dist (`legacy/build/`, so Safari works; Apache-2.0, see pdfjs/LICENSE) | 6.4.299 |

The ProseMirror modules are pulled from `esm.sh` at fixed versions in
`templates/index.html.j2`. Vendoring the full ESM graph would require a
build step, so they're pinned in-line instead.

To upgrade a vendored file, replace it with the new minified bundle
from `https://cdn.jsdelivr.net/npm/<package>@<version>/...` and update
the version row above. pdf.js is loaded only when a page view opens
(templates/assets/js/44-pdf-pages.js); its text-layer CSS is copied into
app.css from the same release's `web/pdf_viewer.css`.
