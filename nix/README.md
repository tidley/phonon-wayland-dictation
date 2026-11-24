# NixOS integration

Start with the repository's [NixOS installation guide](../README.md#nixos-installation).
The configuration is reusable: set your own username, checkout/runtime-shell
path and virtualenv path in the module options. No workstation-specific
configuration is required by these files.

## Files

- `helper.nix`: locked Rust engine build, libxkbcommon dependency, and generated
  IBus descriptor; exports `meta.isIbusEngine` for NixOS's engine option.
- `module.nix`: `services.phonon-dictation` options, additive IBus engine
  registration, standard ydotool configuration, and a graphical-login user
  service using the separate virtualenv with `--output auto`.
- `shell.nix`: Python/runtime dependencies, native Rust toolchain, GI integration
  test dependencies and developer tools. Cargo output goes to
  `build/nixos/ibus-helper`, leaving Debian's target and `.venv` intact.

The module's required options are `user`, `shellFile`, and `venv` when `enable`
is true. Paths for the runtime shell and virtualenv are absolute strings; they
must remain accessible at login. The helper source is copied into the Nix store
without Cargo targets, so shared-checkout build artefacts are not packaged.

## Standalone builds and checks

From the repository root, build the engine without activating system services:

```bash
mkdir -p build/nixos
nix-build -E 'let pkgs = import <nixpkgs> {}; in pkgs.callPackage ./nix/helper.nix {}' --out-link build/nixos/helper
```

Build an isolated IBus package containing the engine:

```bash
nix-build -E 'let pkgs = import <nixpkgs> {}; in pkgs.ibus-with-plugins.override { plugins = [ (pkgs.callPackage ./nix/helper.nix {}) ]; }' --out-link build/nixos/ibus
nix-shell nix/shell.nix --run 'PATH="$PWD/build/nixos/ibus/bin:$PATH" python rust/ibus-helper/tests/integration.py --packaged --helper build/nixos/helper/bin/phonon-ibus-helper'
```

That package is for isolated tests. The NixOS module merges Phonon into the real
system's configured engine list; do not replace your desktop daemon with this
test package if you use additional engines. The harness starts a private D-Bus
session, cache, runtime directory and daemon. It does not change the desktop
input source or use the clipboard or synthetic input.

For the Rust and Python developer checks:

```bash
nix-shell nix/shell.nix
cargo build --release --locked --manifest-path rust/ibus-helper/Cargo.toml
python rust/ibus-helper/tests/integration.py --helper "$CARGO_TARGET_DIR/release/phonon-ibus-helper"
python rust/ibus-helper/tests/integration.py --installed --helper "$CARGO_TARGET_DIR/release/phonon-ibus-helper"
cargo clippy --locked --manifest-path rust/ibus-helper/Cargo.toml -- -D warnings
cargo fmt --manifest-path rust/ibus-helper/Cargo.toml -- --check
PYTHONPATH=src python -m pytest -q
```

IBus GI bindings suffice for the isolated clients; GTK GI bindings are only
needed for an additional graphical scratch-window test. Audio/hotkey gestures,
clipboard fallback in target applications, login, reboot and rebuild behaviour
are covered by the manual checklist in the main README.
