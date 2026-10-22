"""Copy pinned Git blobs into ignored module temp; no checkout, network, or merge."""
from io import BytesIO
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


def main() -> None:
    module = Path(__file__).resolve().parents[1]
    if module != Path(r"C:\git\shared\infra-pilot\apps\liara\triage").resolve():
        raise RuntimeError("Use the canonical InfraPilot module")
    directory = module / ".tmp/collection_context_sources"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for package, revision in (("provider", "66655e6f21b70717948122bc521b72f54b9d91a8"),
                              ("setup", "7e559255a72134473aac75c1de0c42b21864b061")):
        destination = directory / f"{package}-{revision[:7]}"
        destination.mkdir(exist_ok=True)
        archive = subprocess.run(["git", "archive", "--format=tar", revision, package],
                                 cwd=module.parents[2], check=True, capture_output=True).stdout
        files = {}
        with tarfile.open(fileobj=BytesIO(archive), mode="r:") as contents:
            for member in contents.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or path.parts[0] != package:
                    raise RuntimeError("Unsafe archive path")
                target = destination.joinpath(*path.parts).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError("Archive escaped module directory")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise RuntimeError("Non-regular archive entry")
                data = contents.extractfile(member).read()
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and target.read_bytes() != data:
                    raise RuntimeError("Source copy conflict; refusing overwrite")
                if not target.exists():
                    with target.open("xb") as output:
                        output.write(data)
                files[member.name] = hashlib.sha256(data).hexdigest()
        manifest[package] = {"revision": revision, "files": files}
        print(f"Verified {len(files)} {package} files at {revision}")
    target = directory / "manifest.json"
    data = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    if target.exists() and target.read_bytes() != data:
        raise RuntimeError("Source manifest conflict")
    if not target.exists():
        with target.open("xb") as output:
            output.write(data)


if __name__ == "__main__":
    main()
