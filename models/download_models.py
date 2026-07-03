import argparse
import getpass
import os

from huggingface_hub import snapshot_download


DEFAULT_REPO_ID = "dragonkue/BGE-m3-ko"
DEFAULT_TARGET_PATH = "./models/embedding/models--dragonkue--BGE-m3-ko"


def download_model(repo_id: str, target_path: str, token: str | None) -> None:
    os.makedirs(target_path, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=target_path,
        token=token,
    )
    print(f"[downloaded] {repo_id} -> {target_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the dragonkue embedding model.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--target-path", default=DEFAULT_TARGET_PATH)
    parser.add_argument("--token", default=None, help="Hugging Face token. If omitted, prompt securely.")
    args = parser.parse_args()

    token = args.token
    if token is None:
        token = getpass.getpass("Hugging Face token (blank for public/no token): ").strip() or None

    download_model(args.repo_id, args.target_path, token)


if __name__ == "__main__":
    main()
