# Windows installer

## One-liner

```powershell
irm https://raw.githubusercontent.com/skemadiya2833/open-friday/main/deploy/windows/install.ps1 | iex
```

Installs under `%LOCALAPPDATA%\OpenFriday` (override with `$env:FRIDAY_HOME`).

## Flags (file mode)

```powershell
irm .../install.ps1 -OutFile install.ps1
.\install.ps1 -Force
.\install.ps1 -PullModels              # chat + embed
.\install.ps1 -PullModels -PullVision  # + vision model
```

Under `irm | iex`, use env vars instead: `FRIDAY_FORCE`, `FRIDAY_PULL_MODELS`, `FRIDAY_PULL_VISION`.

## After install

```powershell
friday doctor
friday version
friday                 # Control Center + tray
```

## Uninstall

```powershell
irm https://raw.githubusercontent.com/skemadiya2833/open-friday/main/deploy/windows/uninstall.ps1 | iex
```

Leaves Python, Ollama, git, and uv installed.
