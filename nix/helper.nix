{ lib, rustPlatform, libxkbcommon, python3 }:

rustPlatform.buildRustPackage {
  pname = "phonon-ibus-helper";
  version = "0.1.0";
  src = lib.fileset.toSource {
    root = ../rust/ibus-helper;
    fileset = lib.fileset.unions [
      ../rust/ibus-helper/Cargo.toml
      ../rust/ibus-helper/Cargo.lock
      ../rust/ibus-helper/src
    ];
  };
  cargoLock.lockFile = ../rust/ibus-helper/Cargo.lock;
  buildInputs = [ libxkbcommon ];
  nativeBuildInputs = [ python3 ];
  postInstall = ''
    python ${../install_ibus.py} --descriptor "$out/share/ibus/component" \
      --helper "$out/bin/phonon-ibus-helper"
  '';
  meta = {
    description = "Native IBus dictation input source for Phonon";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    isIbusEngine = true;
  };
}
