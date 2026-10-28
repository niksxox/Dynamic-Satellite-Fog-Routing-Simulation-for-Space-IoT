import json
import sys
from pathlib import Path

# Ensure backend root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "backend"))

from app.schemas import Frame

def main():
    sample_file = root_dir / "docs" / "sample_frame.json"
    if not sample_file.exists():
        print(f"Error: {sample_file} not found.")
        sys.exit(1)

    with open(sample_file, "r") as f:
        data = json.load(f)

    try:
        frame = Frame.model_validate(data)
        print("docs/sample_frame.json validated successfully against app.schemas.Frame!")
        print(f"  Timestamp: {frame.t}s, Sats: {len(frame.sats)}, Links: {len(frame.links)}, Flows: {len(frame.flows)}")
    except Exception as e:
        print(f"✗ Validation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
