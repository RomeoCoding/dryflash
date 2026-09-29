"""A fake GDB speaking just enough GDB/MI for the unit tests of esp32_sim_mcp.gdbmi."""

import re
import sys
import time

FRAME0 = 'frame={level="0",addr="0x400d5a18",func="app_main",file="main/app.c",fullname="/w/main/app.c",line="10"}'
FRAME1 = 'frame={level="1",addr="0x400e7c2c",func="main_task",file="app_startup.c",fullname="/idf/app_startup.c",line="208"}'
STOP_FRAME = 'frame={addr="0x400d5a18",func="app_main",args=[],file="main/app.c",fullname="/w/main/app.c",line="10"}'


def out(s):
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


out('=thread-group-added,id="i1"')
out("(gdb)")
bp_set = False
for raw in sys.stdin:
    m = re.match(r"(\d*)(\S+)\s*(.*)", raw.strip())
    if not m:
        continue
    tok, cmd, args = m.groups()
    if cmd in ("-gdb-set", "-file-exec-and-symbols", "-enable-pretty-printing"):
        out(f"{tok}^done")
    elif cmd == "-target-select":
        out(f"{tok}^connected")
        out(f'*stopped,{STOP_FRAME},thread-id="1",stopped-threads="all"')
    elif cmd == "-break-insert":
        if args.strip() == "nosuchfn":
            out(f'{tok}^error,msg="Function \\"nosuchfn\\" not defined."')
        else:
            bp_set = True
            out(f'{tok}^done,bkpt={{number="1",type="breakpoint",disp="keep",enabled="y",addr="0x400d5a18",'
                f'func="app_main",file="main/app.c",fullname="/w/main/app.c",line="10",times="0"}}')
    elif cmd == "-exec-continue":
        out(f"{tok}^running")
        out('*running,thread-id="all"')
        # Without a breakpoint the target "runs forever", which exercises the timeout path.
        if bp_set:
            time.sleep(0.1)
            out(f'*stopped,reason="breakpoint-hit",disp="keep",bkptno="1",{STOP_FRAME},thread-id="1"')
    elif cmd == "-exec-interrupt":
        out(f"{tok}^done")
        out(f'*stopped,reason="signal-received",signal-name="SIGINT",{STOP_FRAME},thread-id="1"')
    elif cmd in ("-exec-next", "-exec-step", "-exec-finish", "-exec-next-instruction"):
        out(f"{tok}^running")
        out('*running,thread-id="all"')
        out(f'*stopped,reason="end-stepping-range",{STOP_FRAME.replace(chr(34) + "10" + chr(34), chr(34) + "11" + chr(34))},thread-id="1"')
    elif cmd == "-stack-list-frames":
        out(f"{tok}^done,stack=[{FRAME0},{FRAME1}]")
    elif cmd == "-data-list-register-names":
        out(f'{tok}^done,register-names=["pc","ar0","ar1","","sar"]')
    elif cmd == "-data-list-register-values":
        out(f'{tok}^done,register-values=[{{number="0",value="0x400d5a18"}},{{number="1",value="0x800d5a33"}},'
            f'{{number="2",value="0x3ffb45f0"}},{{number="4",value="0x4"}}]')
    elif cmd == "-data-read-memory-bytes":
        out(f'{tok}^done,memory=[{{begin="0x3ffb0000",offset="0x0",end="0x3ffb0004",contents="deadbeef"}}]')
    elif cmd == "-data-evaluate-expression":
        if "bad" in args:
            out(f'{tok}^error,msg="No symbol \\"bad\\" in current context."')
        else:
            out(f'{tok}^done,value="42"')
    elif cmd == "-gdb-exit":
        out(f"{tok}^exit")
        break
    else:
        out(f'{tok}^error,msg="Undefined MI command: {cmd}"')
    out("(gdb)")
