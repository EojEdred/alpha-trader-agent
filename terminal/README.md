# Alpha Trader Terminal (Fincept UI)

This is the desktop UI. Source lives in `fincept-qt/`. License is AGPL-3.0
(see `LICENSE`).

## Run the already-installed binary

The v4.5.0 app is at `/Applications/FinceptTerminal.app`. Dexter must be
running so the Alpha Trader desk can load:

```bash
python cli.py platform start
```

The in-tree screen (`src/screens/alpha_trader/`) is compiled into a custom
binary. The stock 4.5.0 app does not yet contain that screen until you
build this tree with Qt 6.8.3.

## Build from this tree (Qt 6.8.3 required)

```bash
export QT_DIR=~/Qt/6.8.3/macos
cd terminal/fincept-qt
cmake --preset macos-release
cmake --build --preset macos-release
open ./build/macos-release/FinceptTerminal.app
```

Pinned toolchain: CMake 3.27+ · Qt 6.8.3 · Python 3.11 · Xcode 15.2+.
See `docs/GETTING_STARTED.md`.
