import importlib
import json
import os
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
        if os.environ.get("AJA_SMOKE") == "1":
            # Smoke test on a clean folder: skip the GUI wizard entirely and
            # fall through to the smoke-exit handle below.
            pass
        else:
            return run_setup()

    # Returning customer with a config: if they are still on the Free plan (no
    # license key saved) and aren't in an automated/smoke run, pop the wizard's
    # "Unlock" step so they can enter their Gumroad key before the bot starts.
    if not os.environ.get("AJA_SMOKE") == "1" and _on_free_plan(config_path):
        print("No license key yet - opening the Unlock step to activate unlimited applications.")
        try:
            import setup_wizard
            setup_wizard.run_gui(initial_step="unlock")
        except Exception as e:
            print("Could not open the Unlock window:", e)

    if os.environ.get("AJA_SMOKE") == "1":
        if getattr(sys, "frozen", False):
            print("AJA exe smoke OK")
        else:
            importlib.import_module("runAiBot")
            print("runAiBot import OK")
        return 0

    return run_bot()


def _on_free_plan(config_path: str) -> bool:
    '''True if user_config.json holds no active license key (Free plan).'''
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        key = (data.get("secrets", {}).get("gumroad_license_key") or "").strip()
        return not bool(key)
    except (OSError, ValueError):
        return False


def run_setup() -> int:
    import setup_wizard
    setup_wizard.run_gui()
    return 0


def run_bot() -> int:
    # Bundled exe: run the engine from inside the package (all modules ship in
    # the onefile). Source checkout: run it directly too.
    runAiBot = importlib.import_module("runAiBot")
    runAiBot.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())