from pathlib import Path


Path("fixture-destructive-marker.txt").write_text("executed", encoding="utf-8")
