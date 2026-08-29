import importlib
import os
import subprocess
import sys


def app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    base = app_base_dir()
    os.chdir(base)
    if base not in sys.path:
        sys.path.insert(0, base)

    args = [a for a in sys.argv[1:]]

    if "--probe" in args:
        import setup_wizard
        i = args.index("--probe")
        out = args[i + 1] if len(args) > i + 1 else None
        setup_wizard.probe_write(out)
        return 0

    if "--setup" in args:
        return run_setup()

    config_path = os.path.join(base, "user_config.json")
    if not os.path.exists(config_path):
        return run_setup()

    if os.environ.get("AJA_SMOKE") == "1":
        if getattr(sys, "frozen", False):
            print("AJA exe smoke OK")
        else:
            importlib.import_module("runAiBot")
            print("runAiBot import OK")
        return 0

    return run_bot()


def run_setup() -> int:
    import setup_wizard
    setup_wizard.run_gui()
    return 0


def run_bot() -> int:
    run_bat = os.path.join(app_base_dir(), "start_bot.bat")
    if getattr(sys, "frozen", False):
        print("AutoJobApplier.exe: launching the app engine...\n")
        return subprocess.call(["cmd", "/c", run_bat])
    runAiBot = importlib.import_module("runAiBot")
    runAiBot.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())