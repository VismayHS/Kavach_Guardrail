"""Shell commands and scripts an agent writes (E10): read them, dry-run them where they can't hurt, then decide.

Before E10, KAVACH had no model of a shell command, so `Bash` was judged as "irreversible, may reach the network"
and escalated. E10 closes most of that gap with two checks, the same idea as the rest of KAVACH (decide on what the
action really does, not on what the agent says it does):

1. Static reading (`analyze`), deterministic: every program in every pipeline segment, subshell and `-c` string,
   and what it reaches: network egress (curl, wget, nc, ssh, scp, /dev/tcp, python/node sockets), secrets (.env,
   id_rsa, ~/.aws, printenv), privilege (sudo, su, setuid), persistence (crontab, shell rc files, authorized_keys,
   systemd), decode-and-run (curl | sh, base64 -d | bash, eval), and writes or deletes outside the workspace.
2. Dry run (`DockerSandbox.stage`): the command runs in a throwaway container on a copy of the workspace with no
   network, a read-only root, no capabilities, a memory, CPU and process cap and a time limit. KAVACH diffs the copy
   (files created, changed, deleted) and reads the exit status: the effect is measured, not guessed.

Approved commands run the same way on the real workspace, still with no network (`DockerSandbox.run`); the files they
change are snapshotted first, so Undo restores them. Without Docker the server never runs a shell command on its own
host: it can still judge commands for an agent that runs them itself (the Claude Code hook), from the static reading.

Honest scope: this reads and contains commands; it is not Kairos's system-boundary enforcement on a live trace. A
command can hide intent the reader misses (e.g. a script it downloads later); the sandbox's missing network and the
no-host-execution rule are what bound the damage then.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from pathlib import Path

NETWORK = {"curl", "wget", "nc", "ncat", "netcat", "ssh", "scp", "sftp", "rsync", "ftp", "tftp", "telnet", "socat",
           "http", "https", "aria2c", "lynx", "links", "nmap", "ping", "dig", "nslookup", "host", "git-remote-http"}
GIT_NET = {"push", "pull", "fetch", "clone", "ls-remote", "submodule"}
PKG_NET = {("pip", "install"), ("pip3", "install"), ("npm", "install"), ("npm", "publish"), ("yarn", "add"),
           ("apt", "install"), ("apt-get", "install"), ("brew", "install"), ("gem", "install"), ("cargo", "install")}
PRIVILEGE = {"sudo", "su", "doas", "pkexec", "setcap", "chroot", "nsenter", "mount", "insmod", "modprobe"}
PERSISTENCE_CMD = {"crontab", "at", "launchctl", "systemctl", "update-rc.d", "chkconfig"}
PERSISTENCE_PATH = re.compile(r"(\.bashrc|\.zshrc|\.profile|\.bash_profile|authorized_keys|/etc/cron|/etc/systemd|"
                              r"LaunchAgents|LaunchDaemons|/etc/rc\.local|/etc/profile)")
SECRET_PATH = re.compile(r"(^|[/\s'\"=])(\.env\b|[\w.-]*\.env\b|id_rsa|id_ed25519|\.ssh/|\.aws/|\.kube/config|"
                         r"\.netrc|\.npmrc|\.pypirc|/etc/shadow|credentials|secrets?\b|\.pem\b|\.key\b|token)", re.I)
SECRET_CMD = {"printenv", "env", "set", "export"}            # dumping the environment exposes every key in it
DESTRUCTIVE = {"rm", "rmdir", "shred", "mkfs", "dd", "truncate", "wipefs", "fdisk", "unlink"}
RUNNERS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "python", "python3", "node", "perl", "ruby", "php"}
DECODERS = {"base64", "xxd", "openssl", "gunzip", "zcat", "uudecode"}
NET_CODE = re.compile(r"(import\s+(socket|requests|urllib|http\.client|httpx|aiohttp|ftplib|smtplib)|"
                      r"from\s+(urllib|requests|http|httpx)|urlopen\(|require\(['\"](https?|net|axios|node-fetch)|"
                      r"fetch\(|/dev/(tcp|udp)/|socket\.socket|Net::HTTP|LWP::|curl_exec)")
URL = re.compile(r"\b(?:https?|ftp|ssh|git)://([^/\s:'\"]+)|\b[\w.-]+@([\w-]+(?:\.[\w-]+)+):")


def _split_top(cmd: str) -> list[tuple[str, str]]:
    """Split on | || && ; & and newlines outside quotes: [(segment, operator after it)]."""
    out, cur, q, i = [], [], None, 0
    while i < len(cmd):
        c = cmd[i]
        if q:
            cur.append(c)
            if c == "\\" and q == '"' and i + 1 < len(cmd):
                cur.append(cmd[i + 1])
                i += 1
            elif c == q:
                q = None
        elif c in "'\"":
            q = c
            cur.append(c)
        elif c == "\\" and i + 1 < len(cmd):
            cur += [c, cmd[i + 1]]
            i += 1
        elif c in "|&;\n":
            op = cmd[i:i + 2] if cmd[i:i + 2] in ("||", "&&") else c
            if c == "&" and (cmd[i - 1:i] in (">", "<") or cmd[i + 1:i + 2] == ">"):   # 2>&1, &> are redirects
                cur.append(c)
                i += 1
                continue
            out.append(("".join(cur), op))
            cur = []
            i += len(op)
            continue
        else:
            cur.append(c)
        i += 1
    out.append(("".join(cur), ""))
    return [(a.strip(), op) for a, op in out if a.strip()]


def _segments(cmd: str) -> list[str]:
    """Top-level pipeline and list segments, plus the inside of $(...), `...` and <(...)."""
    inner = re.findall(r"\$\(([^()]*)\)|`([^`]*)`|<\(([^()]*)\)", cmd)
    return [a for a, _ in _split_top(cmd)] + [x.strip() for t in inner for x in t if x and x.strip()]


def _words(seg: str) -> list[str]:
    try:
        return shlex.split(seg, comments=True)
    except ValueError:
        return seg.split()


def _program(words: list[str]) -> tuple[str, list[str]]:
    """The program a segment runs, past VAR=value assignments and wrappers (sudo is reported separately)."""
    i = 0
    while i < len(words) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[i]):
        i += 1
    rest = words[i:]
    while rest and rest[0] in ("time", "nohup", "nice", "exec", "command", "builtin", "xargs", "env", "timeout",
                               "stdbuf") and len(rest) > 1:
        rest = rest[1:]
        while rest and (rest[0].startswith("-") or re.fullmatch(r"\d+[smh]?", rest[0])):
            rest = rest[1:]
    return (os.path.basename(rest[0]) if rest else ""), rest[1:]


def _outside(path: str) -> bool:
    p = path.strip("'\"")
    return p.startswith(("/", "~")) and not p.startswith(("/tmp", "/dev/null", "/work")) or p.startswith("..") \
        or "/../" in p


def analyze(command: str, depth: int = 0) -> dict:
    """What a shell command reaches, read without running it."""
    out = {"programs": [], "network": [], "hosts": [], "secrets": [], "privilege": [], "persistence": [],
           "destructive": [], "outside_writes": [], "decode_and_run": [], "runs_code": False, "parse_error": None}
    if not command.strip():
        out["parse_error"] = "empty command"
        return out
    try:
        shlex.split(command, comments=True)
    except ValueError as e:
        out["parse_error"] = str(e)
    segs = _segments(command)
    progs_in_order = []
    for seg in segs:
        words = _words(seg)
        prog, args = _program(words)
        if not prog:
            continue
        progs_in_order.append(prog)
        out["programs"].append(prog)
        joined = " ".join(args)
        if words and words[0] in PRIVILEGE or prog in PRIVILEGE:
            out["privilege"].append(words[0] if words and words[0] in PRIVILEGE else prog)
        if prog in ("chmod",) and re.search(r"(\+s|[2467][0-7]{3}\b|u\+s)", joined):
            out["privilege"].append("setuid bit")
        if prog in NETWORK or (prog == "git" and args and args[0] in GIT_NET) or \
                (prog, args[0] if args else "") in PKG_NET:
            out["network"].append(prog if prog != "git" else f"git {args[0]}")
        if prog in PERSISTENCE_CMD:
            out["persistence"].append(prog)
        if PERSISTENCE_PATH.search(seg):
            out["persistence"].append(PERSISTENCE_PATH.search(seg).group(1))
        if prog in SECRET_CMD and not args:
            out["secrets"].append(f"{prog} (dumps every environment variable)")
        for w in args:
            if SECRET_PATH.search(w):
                out["secrets"].append(w)
        if prog in DESTRUCTIVE or (prog == "find" and "-delete" in args) or \
                (prog == "git" and args[:1] in (["reset"], ["clean"]) and any(a in ("--hard", "-f", "-fd", "-fdx")
                                                                              for a in args)) or \
                (prog == "git" and args[:1] == ["push"] and any(a in ("-f", "--force") for a in args)):
            out["destructive"].append(seg[:80])
            out["outside_writes"] += [a for a in args if not a.startswith("-") and _outside(a)]
            if prog == "rm" and any(a.strip("'\"") in ("/", "/*", "~", "~/", ".", "./", "*", "..") for a in args):
                out["outside_writes"].append("everything (rm on / ~ . or *)")
        if prog in ("cp", "mv", "tee", "touch", "mkdir", "ln", "install", "chmod", "chown", "sed") and \
                any(_outside(a) for a in args if not a.startswith("-")):
            out["outside_writes"] += [a for a in args if not a.startswith("-") and _outside(a)][-1:]
        for m in re.finditer(r">>?\s*([^\s;|&]+)", seg):
            if _outside(m.group(1)):
                out["outside_writes"].append(m.group(1))
        if prog in RUNNERS:
            out["runs_code"] = True
            code = None
            if "-c" in args and args.index("-c") + 1 < len(args):
                code = args[args.index("-c") + 1]
            elif prog in ("python", "python3", "node", "perl", "ruby", "php") and "-e" in args:
                code = args[args.index("-e") + 1] if args.index("-e") + 1 < len(args) else ""
            if code:
                if NET_CODE.search(code):
                    out["network"].append(f"{prog} code that opens a connection")
                if prog in ("sh", "bash", "zsh", "dash", "ksh") and depth < 3:
                    sub = analyze(code, depth + 1)
                    for k in ("network", "hosts", "secrets", "privilege", "persistence", "destructive",
                              "outside_writes", "decode_and_run"):
                        out[k] += sub[k]
        if prog == "eval":
            out["decode_and_run"].append("eval")
        if "/dev/tcp/" in seg or "/dev/udp/" in seg:
            out["network"].append("/dev/tcp")
    # decode-and-run: content that is fetched or decoded, then piped into an interpreter
    top = _split_top(command)
    for (a, op), (b, _) in zip(top, top[1:]):
        if op != "|":
            continue
        pa, _ = _program(_words(a))
        pb, bargs = _program(_words(b))
        if pb in RUNNERS and not (pb in ("python", "python3", "node") and bargs and bargs[0] not in ("-", "-c")):
            if pa in NETWORK or pa in DECODERS or "base64" in a or "curl" in a or "wget" in a:
                out["decode_and_run"].append(f"{pa} | {pb}")
    if re.search(r"(sh|bash)\s+-c\s+[\"']?\$\((curl|wget)", command) or re.search(r"<\((curl|wget)", command):
        out["decode_and_run"].append("runs a downloaded script")
    out["hosts"] = sorted({h for m in URL.finditer(command) for h in m.groups() if h})
    for k in ("programs",):
        out[k] = list(dict.fromkeys(out[k]))
    for k in ("network", "secrets", "privilege", "persistence", "destructive", "outside_writes", "decode_and_run"):
        out[k] = list(dict.fromkeys(out[k]))[:10]
    return out


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def _diff(before: dict[str, bytes], after: dict[str, bytes]) -> dict:
    return {"created": sorted(set(after) - set(before)), "deleted": sorted(set(before) - set(after)),
            "changed": sorted(n for n in set(before) & set(after) if before[n] != after[n])}


# Inside the container: copy the (read-only) workspace into a size-capped tmpfs, run the command there, then send the
# resulting tree and the command's output back as one tar on stdout. The command never writes to the host.
_SCRIPT = ('cp -a /src/. /work/ 2>/dev/null; cd /work; mkdir -p /tmp/.kavach; '
           'sh -c "$1" >/tmp/.kavach/out 2>/tmp/.kavach/err </dev/null; echo $? >/tmp/.kavach/rc; '
           'tar -cf - -C /work . -C /tmp .kavach 2>/dev/null')


class DockerSandbox:
    """Runs a command in a throwaway container: no network, read-only root, no capabilities, capped memory, CPU,
    processes, disk (64 MB tmpfs) and time. The workspace is mounted read-only; the command works on a copy in the
    tmpfs. `stage` reports what changed; `run` (an approved command) then applies exactly those changes."""

    def __init__(self, image: str | None = None, timeout_s: float = 10.0, docker: str = "docker",
                 disk_mb: int = 64):
        self.image = image or os.environ.get("KAVACH_SHELL_IMAGE", "python:3.13-slim")
        self.timeout_s, self.docker, self.disk_mb = float(timeout_s), docker, int(disk_mb)
        self._ok: bool | None = None

    def available(self) -> bool:
        if self._ok is None:
            try:
                r = subprocess.run([self.docker, "image", "inspect", self.image], capture_output=True, timeout=20)
                self._ok = r.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                self._ok = False
        return self._ok

    def _argv(self, workspace: Path, command: str, name: str) -> list[str]:
        return [self.docker, "run", "--rm", "--name", name, "--network", "none", "--read-only",
                "--tmpfs", "/tmp:rw,size=16m,mode=1777", "--tmpfs", f"/work:rw,size={self.disk_mb}m,mode=1777",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64",
                "--memory", "256m", "--cpus", "1", "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
                "-v", f"{Path(workspace).resolve()}:/src:ro", self.image, "sh", "-c", _SCRIPT, "kavach", command]

    def _exec(self, workspace: Path, command: str) -> tuple[dict, dict[str, bytes] | None]:
        import io
        import tarfile
        name = f"kavach-sh-{os.getpid()}-{int(time.time() * 1000) % 10**9}"
        t0 = time.perf_counter()
        try:
            r = subprocess.run(self._argv(workspace, command, name), capture_output=True, timeout=self.timeout_s)
            raw, timed_out = r.stdout, False
        except subprocess.TimeoutExpired:
            subprocess.run([self.docker, "rm", "-f", name], capture_output=True)
            raw, timed_out = b"", True
        tree, meta = {}, {}
        try:
            with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
                for m in tf.getmembers():
                    if not m.isfile():
                        continue
                    data = tf.extractfile(m).read()
                    n = m.name[2:] if m.name.startswith("./") else m.name
                    if n.startswith(".kavach/"):
                        meta[n[len(".kavach/"):]] = data.decode(errors="replace")
                    else:
                        tree[n] = data
        except tarfile.TarError:
            tree = None
        so, se = meta.get("out", ""), meta.get("err", "")
        rc = meta.get("rc", "").strip()
        net = bool(re.search(r"(Could not resolve host|Temporary failure in name resolution|Network is unreachable|"
                             r"Name or service not known|getaddrinfo|No address associated)", se + so))
        out = {"exit": int(rc) if rc.lstrip("-").isdigit() else None, "timed_out": timed_out,
               "stdout": so[-2000:], "stderr": se[-2000:], "network_attempted": net,
               "ms": round((time.perf_counter() - t0) * 1000)}
        return out, (tree if not timed_out and rc else None)

    def stage(self, command: str, workspace: Path) -> dict:
        """Dry run: what the command would create, change and delete. The workspace is only read."""
        out, tree = self._exec(Path(workspace), command)
        out["files"] = _diff(_tree(Path(workspace)), tree) if tree is not None else None
        return out

    def run(self, command: str, workspace: Path) -> dict:
        """An approved command: run it the same way, then apply exactly the files it changed to the workspace."""
        ws = Path(workspace)
        before = _tree(ws)
        out, tree = self._exec(ws, command)
        if tree is None:
            out["files"] = None
            return out
        d = _diff(before, tree)
        for n in d["deleted"]:
            (ws / n).unlink(missing_ok=True)
        for n in d["created"] + d["changed"]:
            dest = (ws / n).resolve()
            if ws.resolve() not in dest.parents:
                continue                                  # a path that escapes the workspace is never written
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(tree[n])
        out["files"] = d
        return out
