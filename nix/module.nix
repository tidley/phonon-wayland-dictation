{ config, lib, pkgs, utils, ... }:
let
  cfg = config.services.phonon-dictation;
in {
  options.services.phonon-dictation = {
    enable = lib.mkEnableOption "Phonon native IBus dictation";
    user = lib.mkOption { type = lib.types.str; description = "Dictation user's login name"; };
    shellFile = lib.mkOption {
      type = lib.types.str;
      description = "Absolute path to the runtime Nix shell (not copied to the store)";
    };
    venv = lib.mkOption {
      type = lib.types.str;
      description = "Absolute path to the separate NixOS Python virtualenv";
    };
  };
  config = lib.mkIf cfg.enable {
    i18n.inputMethod = {
      enable = true;
      type = "ibus";
      # NixOS merges this list with all engines configured elsewhere.
      ibus.engines = [ (pkgs.callPackage ./helper.nix {}) ];
    };
    programs.ydotool.enable = true;
    hardware.uinput.enable = true;
    users.users.${cfg.user}.extraGroups = [ "input" "ydotool" ];
    systemd.user.services.phonon-dictation = {
      description = "Phonon-2 push-to-talk dictation";
      wantedBy = [ "graphical-session.target" ];
      after = [ "graphical-session.target" "pipewire.service" ];
      partOf = [ "graphical-session.target" ];
      unitConfig.ConditionUser = cfg.user;
      serviceConfig = {
        Type = "simple";
        Environment = "YDOTOOL_SOCKET=/run/ydotoold/socket";
        ExecStart = utils.escapeSystemdExecArgs [
          "${pkgs.nix}/bin/nix-shell" cfg.shellFile "--run"
          "source ${lib.escapeShellArg (cfg.venv + "/bin/activate")} && exec phonon-dictate --output auto"
        ];
        Restart = "on-failure";
        RestartSec = 3;
      };
    };
  };
}
