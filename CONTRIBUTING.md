# Contributing to proseview

Proseview is a small tool with a clear scope: a local dashboard and AI
harness for Markdown-first novel repos. Contributions that sharpen
that purpose are welcome. Things that drag scope outward (cloud sync,
opinionated AI workflows, account systems) are not.

## 🛠️ Setting up

```bash
git clone https://github.com/ourarash/prosview.git
cd prosview
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the tests:

```bash
pytest
```

The suite is fast (~2 seconds) and runs against the synthetic novel
in `fixtures/demo-repo`. New behavior should land with a test there or
in `tests/`.

To exercise the live dashboard while you work:

```bash
proseview --root fixtures/demo-repo
```

A browser tab opens at `http://localhost:7842`. Edits to
`proseview/templates/assets/...` hot-reload via the asset watcher.
Edits to Python require a server restart.

## 🧭 What's where

```
proseview/
├── cli.py                 entry points (serve, init)
├── server.py              HTTP server, save-scene, terminal PTY
├── generator.py           Jinja-rendered HTML + build_scene_data()
├── config.py              .proseview.yaml loader (PyYAML)
├── scenes.py              scene parsing, scan_todos / scan_notes
├── lexical.py             MATTR / MTLD / shape analysis
├── highlights.py          nine prose-pass detectors
├── repo.py                file-tree builder
├── related.py             related-doc heuristic
├── history.py             git-history-driven goals + velocity
├── watch.py               polling file watcher
├── editor.py              vscode/cursor/zed/positron URL builder
├── goals.py               daily / streak / chapter goal computation
└── templates/
    ├── index.html.j2
    └── assets/
        ├── app.css        single stylesheet
        └── js/            topical files concatenated at render time

tests/                     pytest suite
fixtures/demo-repo/        synthetic novel for tests
plans/                     roadmap / design notes
```

The front-end is split across nine topical files in
`templates/assets/js/` and concatenated at render time. There's no
build step. Add a new file and it'll be picked up automatically; just
make sure it's named so it sorts where you want it in the bundle.

## ✅ Pull requests

1. **Open an issue first** for anything bigger than a typo or a small
   bug fix, so we can agree on shape before you write code.
2. **Keep PRs focused.** One logical change per PR.
3. **Tests pass.** `pytest` is required to be green. CI will block
   anything red.
4. **No new dependencies** without discussion. The current footprint
   is tiny on purpose.
5. **Match the existing voice** in user-facing strings, comments, and
   the README. Small, declarative, explanatory rather than promotional.

## 🪲 Filing bugs

Include:

- The proseview command you ran (`proseview --root ...`).
- Your `.proseview.yaml` if you have one, redacted as needed.
- A minimal scene file or excerpt that reproduces.
- What you saw vs what you expected.

If the bug is in the browser, paste the relevant DevTools Console
errors and the output of:

```js
JSON.stringify({version: 'main', view: document.documentElement.dataset.view})
```

## 📜 License

By contributing you agree your work is licensed under the same MIT
terms as the rest of the project. See [LICENSE](LICENSE).
