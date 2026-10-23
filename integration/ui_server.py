"""Local explicit-Mock UI server; python -B -m integration.ui_server --mock."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="InfraPilot local Mock UI; no Liara connection or executor")
    parser.add_argument("--mock", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data-directory", default=".tmp/ui-demo")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Invalid local port")
    from .ui_backend import create_ui_app
    import uvicorn
    directory = Path(args.data_directory)
    directory.mkdir(parents=True, exist_ok=True)
    app = create_ui_app(mock=True, data_directory=directory,
                        origins=("http://127.0.0.1:4173", "http://localhost:4173",
                                 f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"),
                        static_directory=Path(__file__).resolve().parents[1] / "apps/web/dist/client")
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
