# Install Proseview on Windows. In PowerShell:
# (Served from GitHub's raw files as text: GitHub Pages sends .ps1 as a
# binary download, which `irm | iex` may not run.)
#
#   irm https://raw.githubusercontent.com/ourarash/proseview/main/site/install.ps1 | iex
#
# Nothing else needs to be installed first, and no administrator rights are
# needed. It installs uv (https://docs.astral.sh/uv/), which brings its own
# Python, uses it to install Proseview, asks where your book is, adds a
# Proseview shortcut to the Desktop and the Start menu, and opens the book.
# Run it again to update.

$ErrorActionPreference = 'Stop'
$Package = if ($env:PROSEVIEW_PACKAGE) { $env:PROSEVIEW_PACKAGE } else { 'proseview[claude]' }

function Fail($message) {
    Write-Host "Proseview could not be installed: $message" -ForegroundColor Red
    throw $message
}

Write-Host ''
Write-Host 'Installing Proseview, a writing studio for novels in plain Markdown.'
Write-Host ''

# 1. uv, which installs Proseview and the Python it runs on.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Installing uv, which brings its own Python...'
    $env:UV_NO_MODIFY_PATH = '1'
    try { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression | Out-Null }
    catch { Fail 'uv did not install. See https://docs.astral.sh/uv/ for other ways to get it.' }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail 'uv was installed but cannot be found. Open a new PowerShell window and run this again.'
}

# 2. Proseview itself. Running this again updates it.
Write-Host 'Installing Proseview...'
uv tool install --quiet --upgrade $Package
if ($LASTEXITCODE -ne 0) { Fail 'uv could not install Proseview.' }
uv tool update-shell *> $null  # So `proseview` works in new windows.
$BinDir = (uv tool dir --bin).Trim()
$Proseview = Join-Path $BinDir 'proseview.exe'
if (-not (Test-Path $Proseview)) { Fail "Proseview was installed but $Proseview is missing." }

# 3. Where the book is.
$Documents = [Environment]::GetFolderPath('MyDocuments')
$DefaultBook = Join-Path $Documents 'Proseview\MyNovel'
Write-Host ''
Write-Host 'Where is your book?'
Write-Host '  - Press Enter to start a new one in Documents\Proseview\MyNovel'
Write-Host "  - Or drag your book's folder into this window, then press Enter"
$answer = (Read-Host '>').Trim().Trim('"').Trim("'")

if (-not $answer) {
    & $Proseview new $DefaultBook --no-serve
    $Book = $DefaultBook
} else {
    if (-not (Test-Path -LiteralPath $answer -PathType Container)) {
        Fail "`"$answer`" is not a folder. Run the installer again and drag in your book's folder."
    }
    & $Proseview open $answer --no-serve
    $Book = $answer
}
if ($LASTEXITCODE -ne 0) { Fail 'Proseview could not set up your book.' }

# 4. Shortcuts: double-click one to open the last book.
$Shell = New-Object -ComObject WScript.Shell
$Places = @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('Programs')) ''))
foreach ($place in $Places) {
    if (-not $place -or -not (Test-Path $place)) { continue }
    $link = $Shell.CreateShortcut((Join-Path $place 'Proseview.lnk'))
    $link.TargetPath = $Proseview
    $link.WorkingDirectory = [Environment]::GetFolderPath('UserProfile')
    $link.Description = 'Open your book in Proseview'
    $link.Save()
}
Write-Host 'Added Proseview to your Desktop and Start menu. Double-click it to open your book.'

Write-Host ''
Write-Host 'Proseview is installed.'
Write-Host '  Open your book:      double-click Proseview, or run: proseview'
Write-Host '  Choose another book: proseview open'
Write-Host '  Start a new book:    proseview new'
Write-Host '  Update Proseview:    run this installer again'
Write-Host ''
Write-Host "Opening $Book now. Keep this window open while you write; close it to stop."
Write-Host ''
& $Proseview --root $Book
