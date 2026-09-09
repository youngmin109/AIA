import json
import pathlib
import sys
payload=json.load(sys.stdin)
with pathlib.Path('hook-input.jsonl').open('a', encoding='utf-8') as f:
    f.write(json.dumps(payload, ensure_ascii=False)+"\n")
print(json.dumps({"decision":"block", "reason":"AIA_TEST_FORBIDDEN_TOOL"}), flush=True)
