"""M1 Q2 follow-up: set tmp105 temperatures via QMP qom-set while the VM is held at -S, then run."""
import json, socket, subprocess, time, os, re
W = "/tmp/app_i2c_attach_esp32"
sock = "/tmp/qmp.sock"
if os.path.exists(sock): os.unlink(sock)
q = subprocess.Popen(["qemu-system-xtensa", "-machine", "esp32", "-nographic", "-no-reboot", "-S",
    "-drive", f"file={W}/flash.bin,if=mtd,format=raw", "-serial", "file:/tmp/u2c.log", "-monitor", "none",
    "-qmp", f"unix:{sock},server=on,wait=off",
    "-device", "tmp105,id=t49,bus=i2c-bus.0,address=0x49",
    "-device", "tmp105,id=t4a,bus=i2c-bus.1,address=0x4a"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
for _ in range(100):
    if os.path.exists(sock): break
    time.sleep(0.05)
s = socket.socket(socket.AF_UNIX); s.connect(sock); f = s.makefile("rw")
def cmd(c, **a):
    f.write(json.dumps({"execute": c, "arguments": a} if a else {"execute": c}) + "\n"); f.flush()
    while True:
        r = json.loads(f.readline())
        if "return" in r or "error" in r: return r
print(json.loads(f.readline())["QMP"]["version"]["qemu"])
print("qmp_capabilities", cmd("qmp_capabilities"))
print("qom-set t49", cmd("qom-set", path="t49", property="temperature", value=31500))
print("qom-set t4a", cmd("qom-set", path="t4a", property="temperature", value=-12250))
print("cont", cmd("cont"))
for _ in range(200):
    if "I2C_ATTACH_DONE" in open("/tmp/u2c.log", errors="replace").read(): break
    time.sleep(0.05)
q.kill()
print("".join(l for l in open("/tmp/u2c.log", errors="replace") if re.match(r"port|probe", l)))
