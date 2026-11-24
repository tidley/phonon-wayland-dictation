{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  packages = with pkgs; [
    (python3.withPackages (ps: with ps; [ evdev pyudev setuptools pip pygobject3 pytest ]))
    uv gcc pkg-config linuxHeaders portaudio stdenv.cc.cc.lib
    wl-clipboard ydotool pipewire ffmpeg curl
    rustc cargo clippy rustfmt libxkbcommon ibus dbus gobject-introspection
  ];
  LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
    pkgs.stdenv.cc.cc.lib pkgs.portaudio pkgs.systemd
  ];
  # Keep the shared checkout's Debian Cargo artefacts and .venv intact.
  shellHook = ''
    export CARGO_TARGET_DIR="${toString ../.}/build/nixos/ibus-helper"
  '';
}
