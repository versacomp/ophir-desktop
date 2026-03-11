import os
import sys
import importlib.util
import inspect
import argparse
import requests
from engine.compiler import compile_strategy_package

# The FastAPI endpoint (to be built next)
CLOUD_URL = "http://localhost:8000/api/v1/deploy"


def cmd_compile(args):
    """Handles the 'ophir compile' command."""
    print(f"\n[SYSTEM] Initiating Headless Compilation...")

    target_dir = os.path.abspath(args.path)
    if not os.path.isdir(target_dir):
        print(f"[ERROR] Strategy directory not found: {target_dir}")
        sys.exit(1)

    zip_name = f"{args.engine}_payload.zip" if args.engine else "cloud_payload.zip"

    print(f"[COMPILER] Target locked: {target_dir}")
    print(f"[COMPILER] Obfuscating strategy via Cython and packaging as {zip_name}...")

    try:
        zip_payload_path = compile_strategy_package(target_dir, zip_name)
        print(f"[COMPILER] 🟢 SUCCESS: Generated secure payload -> {zip_payload_path}\n")
        return zip_payload_path
    except Exception as e:
        print(f"[SYSTEM ERROR] Compilation failed: {str(e)}\n")
        sys.exit(1)


def cmd_deploy(args):
    """Handles the 'ophir deploy' command."""
    # Step 1: Compile the package first
    zip_payload_path = cmd_compile(args)
    zip_filename = os.path.basename(zip_payload_path)

    # Step 2: Transmit to Cloud
    print("[NETWORK] Establishing secure handshake with OphirCloud...")

    try:
        with open(zip_payload_path, 'rb') as f:
            files = {'strategy_file': (zip_filename, f, 'application/zip')}

            metadata = {
                'symbol': args.symbol,
                'user_id': 'usr_mitch_cli_001',
                'timeframe': args.timeframe,
                'engine_name': args.engine or 'UnknownEngine'
            }

            print(f"[NETWORK] Transmitting {zip_filename} payload (Size: {os.path.getsize(zip_payload_path)} bytes)...")
            response = requests.post(CLOUD_URL, files=files, data=metadata, timeout=15)

        if response.status_code == 200:
            resp_json = response.json()
            print(f"[NETWORK] 🟢 SUCCESS: {resp_json.get('message', 'Cloud Node Provisioned!')}")
            print(f"[CLOUD ID] Container ID: {resp_json.get('container_id', 'UNKNOWN')}\n")
        elif response.status_code == 402:
            print("[BILLING] 🔴 DEPLOYMENT REJECTED: Insufficient Execution Credits.\n")
        else:
            print(f"[NETWORK ERROR] Cloud rejected payload: {response.status_code} - {response.text}\n")

    except requests.exceptions.ConnectionError:
        print("[NETWORK FATAL] Could not connect to OphirCloud Registry. Is the FastAPI server running?\n")
    except Exception as e:
        print(f"[SYSTEM ERROR] Deployment sequence failed: {str(e)}\n")


def cmd_backtest(args):
    """Handles the 'ophir backtest' command."""
    print(f"\n[SYSTEM] =========================================")
    print(f"[SYSTEM] Initiating Headless Backtest Engine...")

    target_dir = os.path.abspath(args.path)
    if not os.path.isdir(target_dir):
        print(f"[ERROR] Strategy directory not found: {target_dir}")
        sys.exit(1)

    print(f"[ENGINE] Loading Strategy: {args.engine} from {target_dir}")

    # 1. Temporarily mount the directory to sys.path for local imports
    original_sys_path = sys.path.copy()
    if target_dir not in sys.path:
        sys.path.insert(0, target_dir)

    try:
        # 2. Dynamically load the alpha.py entry point
        entry_file = os.path.join(target_dir, "alpha.py")
        if not os.path.exists(entry_file):
            print(f"[ERROR] Entry point 'alpha.py' missing in {target_dir}")
            sys.exit(1)

        spec = importlib.util.spec_from_file_location("_ophir_strategy", entry_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 3. Instantiate the target engine
        engine_class = getattr(module, args.engine, None)
        if not engine_class:
            print(f"[ERROR] Could not find class '{args.engine}' in alpha.py")
            sys.exit(1)

        active_strategy = engine_class()
        print(f"[ENGINE] 🟢 SUCCESS: {args.engine} armed and ready.")

        # 4. Execute the backtest simulation
        print(f"[DATA] Fetching historical data for {args.symbol} ({args.start_date} to {args.end_date})...")

        # NOTE: This is where you would hook in your actual historical data fetcher
        # and your loop that calls active_strategy.evaluate(candle)
        print("[SIMULATOR] Crunching historical ticks...")

        # Mocking the output for the CLI architecture
        print(f"\n[RESULTS] --- Backtest Complete ---")
        print(f"Symbol: {args.symbol}")
        print(f"Net P/L: +$1,240.50")
        print(f"Win Rate: 64.2%")
        print(f"Max Drawdown: -4.1%")

    except Exception as e:
        print(f"[SYSTEM ERROR] Backtest failed: {str(e)}")
    finally:
        # 5. Clean up the system path
        sys.path = original_sys_path
        print(f"[SYSTEM] =========================================\n")

def main():
    parser = argparse.ArgumentParser(description="OphirTrade Headless Quant CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: compile
    parser_compile = subparsers.add_parser("compile", help="Compile a strategy directory into a secure .zip payload.")
    parser_compile.add_argument("path", help="Path to the strategy directory.")
    parser_compile.add_argument("--engine", help="Name of the main strategy engine class (e.g., CustomAlpha).",
                                default="")

    # Subcommand: deploy
    parser_deploy = subparsers.add_parser("deploy", help="Compile and deploy a strategy to OphirCloud.")
    parser_deploy.add_argument("path", help="Path to the strategy directory.")
    parser_deploy.add_argument("--symbol", help="Ticker symbol to trade.", required=True)
    parser_deploy.add_argument("--timeframe", help="Chart timeframe (e.g., 5m, 1h).", required=True)
    parser_deploy.add_argument("--engine", help="Name of the main strategy engine class.", required=True)

    args = parser.parse_args()

    if args.command == "compile":
        cmd_compile(args)
    elif args.command == "deploy":
        cmd_deploy(args)


if __name__ == "__main__":
    main()