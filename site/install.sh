#!/bin/sh
# Install Proseview on macOS or Linux:
#
#   curl -LsSf https://ourarash.github.io/proseview/install.sh | sh
#
# Nothing else needs to be installed first, and no administrator password is
# asked for. It installs uv (https://docs.astral.sh/uv/), which brings its own
# Python, uses it to install Proseview, asks where your book is, puts a
# Proseview icon on the Desktop and opens the book. Run it again to update.
set -eu

PACKAGE="${PROSEVIEW_PACKAGE:-proseview[claude]}"  # A local path or wheel, for testing.

say() { printf '%s\n' "$*"; }
fail() { printf 'Proseview could not be installed: %s\n' "$*" >&2; exit 1; }

say ""
say "Installing Proseview, a writing studio for novels in plain Markdown."
say ""

# 1. uv, which installs Proseview and the Python it runs on.
if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv, which brings its own Python..."
    command -v curl >/dev/null 2>&1 || fail "curl is needed to download uv."
    curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null \
        || fail "uv did not install. See https://docs.astral.sh/uv/ for other ways to get it."
    PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    export PATH
fi
command -v uv >/dev/null 2>&1 || fail "uv was installed but cannot be found. Open a new terminal and run this again."

# 2. Proseview itself. Running this again updates it.
say "Installing Proseview..."
uv tool install --quiet --upgrade "$PACKAGE" || fail "uv could not install Proseview."
uv tool update-shell >/dev/null 2>&1 || true  # So `proseview` works in new terminals.
BIN_DIR="$(uv tool dir --bin)"
PROSEVIEW="$BIN_DIR/proseview"
[ -x "$PROSEVIEW" ] || fail "Proseview was installed but $PROSEVIEW is missing."

# 3. Where the book is. A piped install has no keyboard on stdin; ask the
#    terminal itself, and fall back to a new book when there is none.
DEFAULT_BOOK="$HOME/Documents/Proseview/MyNovel"
answer=""
if ( : </dev/tty >/dev/tty ) 2>/dev/null; then
    {
        say ""
        say "Where is your book?"
        say "  - Press Enter to start a new one in Documents/Proseview/MyNovel"
        say "  - Or drag your book's folder into this window, then press Enter"
        printf "> "
    } >/dev/tty
    IFS= read -r answer </dev/tty || answer=""
fi

# A folder dragged into Terminal arrives quoted or with escaped spaces.
answer=$(printf '%s' "$answer" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
    -e "s/^'\\(.*\\)'\$/\\1/" -e 's/^"\(.*\)"$/\1/' -e 's/\\\(.\)/\1/g')
case "$answer" in
    "~") answer="$HOME" ;;
    "~/"*) answer="$HOME/${answer#\~/}" ;;
esac

if [ -z "$answer" ]; then
    "$PROSEVIEW" new "$DEFAULT_BOOK" --no-serve
    BOOK="$DEFAULT_BOOK"
else
    [ -d "$answer" ] || fail "\"$answer\" is not a folder. Run the installer again and drag in your book's folder."
    "$PROSEVIEW" open "$answer" --no-serve
    BOOK="$answer"
fi

# 4. A Proseview icon: double-click it to open the last book.
case "$(uname -s)" in
    Darwin)
        if [ -d "$HOME/Desktop" ]; then
            launcher="$HOME/Desktop/Proseview.command"
            cat >"$launcher" <<EOF
#!/bin/sh
# Opens Proseview on your last book. Keep this window open while you write.
exec "$PROSEVIEW"
EOF
            chmod +x "$launcher"
            say "Added Proseview to your Desktop. Double-click it to open your book."
        fi
        ;;
    Linux)
        apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
        mkdir -p "$apps"
        cat >"$apps/proseview.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Proseview
Comment=A writing studio for novels in plain Markdown
Exec="$PROSEVIEW"
Terminal=true
Categories=Office;TextEditor;
EOF
        say "Added Proseview to your applications menu."
        ;;
esac

say ""
say "Proseview is installed."
say "  Open your book:      double-click Proseview, or run: proseview"
say "  Choose another book: proseview open"
say "  Start a new book:    proseview new"
say "  Update Proseview:    run this installer again"
say ""
say "Opening $BOOK now. Keep this window open while you write; close it to stop."
say ""
[ -n "${PROSEVIEW_NO_LAUNCH:-}" ] && exit 0  # For testing the installer.
exec "$PROSEVIEW" --root "$BOOK" </dev/null
