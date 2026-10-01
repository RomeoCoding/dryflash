"""Run a command and write its output as an asciicast v2 file, starting after a marker line."""
import codecs, json, subprocess, sys, time
out_path, marker, cmd = sys.argv[1], sys.argv[2], sys.argv[3:]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
dec = codecs.getincrementaldecoder("utf-8")("replace")
events, t0, seen, start = [], time.monotonic(), "", None
while True:
    chunk = p.stdout.read(65536)
    if not chunk:
        break
    text = dec.decode(chunk)
    now = time.monotonic() - t0
    if start is None:
        seen = (seen + text)[-4000:]
        i = seen.find(marker)
        if i >= 0:
            start = now
            if seen[i + len(marker):]:
                events.append([0.0, "o", seen[i + len(marker):]])
        continue
    events.append([round(now - start, 4), "o", text])
p.wait()
with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps({"version": 2, "width": 100, "height": 34}) + "\n")
    for e in events:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
print("exit", p.returncode, "events", len(events), "duration", events[-1][0] if events else 0)
