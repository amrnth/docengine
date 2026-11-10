"""Mac-side: rent one RunPod GPU, run runpod/job.sh for each model key, pull outputs, always terminate the pod.

Usage:
  RUNPOD_API_KEY=... python runpod/launch.py ovisocr2 olmocr2 chandra2 [--gpu "NVIDIA GeForce RTX 4090"] [--community]

Outputs land in results/<model_key>/ (markdown + _timing.json) and results/<model_key>/_pod.json (price paid).
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://rest.runpod.io/v1"
SSH_KEY = os.path.expanduser(os.environ.get("RUNPOD_SSH_KEY", "~/.ssh/runpod_cheap_inference"))
IMAGE = "vllm/vllm-openai:v0.22.1"
# vllm image has no sshd: install it, authorise RunPod's injected PUBLIC_KEY, then idle.
BOOT = (
    "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server >/dev/null && "
    "mkdir -p /run/sshd ~/.ssh /workspace && echo \"$PUBLIC_KEY\" >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && "
    "chmod 600 ~/.ssh/authorized_keys && /usr/sbin/sshd && sleep infinity"
)


def api(method, path, body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['RUNPOD_API_KEY']}", "Content-Type": "application/json",
                 "User-Agent": "docengine-bench/0.1"},  # Cloudflare blocks Python-urllib's default UA (error 1010)
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        txt = r.read().decode()
        return json.loads(txt) if txt else {}


def sh(cmd, check=True):
    print("+", " ".join(cmd) if isinstance(cmd, list) else cmd, flush=True)
    return subprocess.run(cmd, check=check)


def ssh_base(ip, port):
    return ["ssh", "-i", SSH_KEY, "-p", str(port), "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "ServerAliveInterval=30", "-o", "LogLevel=ERROR", f"root@{ip}"]


def wait_for_ssh(pod_id, timeout=900, ip_timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        pod = api("GET", f"/pods/{pod_id}")
        ip, ports = pod.get("publicIp"), pod.get("portMappings") or {}
        if not ip and time.time() - t0 > ip_timeout:
            raise TimeoutError(f"no public IP after {ip_timeout}s (machine {pod.get('machineId')})")
        if ip and "22" in ports:
            r = subprocess.run(ssh_base(ip, ports["22"]) + ["true"], capture_output=True, timeout=30)
            if r.returncode == 0:
                return pod, ip, ports["22"]
        time.sleep(10)
    raise TimeoutError("pod never became reachable over SSH")


def pack_code():
    path = os.path.join(ROOT, "runpod", f"_code_{os.getpid()}.tar.gz")
    with tarfile.open(path, "w:gz") as t:
        for rel in ["bench/run_vlm.py", "runpod/job.sh", "docengine"]:
            t.add(os.path.join(ROOT, rel), arcname=rel)
        for rel in ["vendor/olmocr", "vendor/chandra"]:
            t.add(os.path.join(ROOT, rel), arcname=rel,
                  filter=lambda ti: None if "/.git" in ti.name or ti.name.endswith(".pdf") else ti)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--gpu", default="NVIDIA GeForce RTX 4090")
    ap.add_argument("--community", action="store_true", help="cheaper Community Cloud instead of Secure Cloud")
    ap.add_argument("--keep", action="store_true", help="do not terminate the pod at the end (debugging)")
    ap.add_argument("--image", default=IMAGE, help="docker image (LightOnOCR-3 needs vllm/vllm-openai:v0.30.0)")
    ap.add_argument("--disk", type=int, default=80, help="container disk GB (Infinity-Parser2-Pro needs ~150)")
    ap.add_argument("--env", action="append", default=[], help="KEY=VALUE passed to job.sh (repeatable)")
    args = ap.parse_args()

    pub = open(SSH_KEY + ".pub").read().strip()
    body = {
        "name": "docengine-bench",
        "imageName": args.image,
        "gpuTypeIds": [args.gpu],
        "gpuCount": 1,
        "cloudType": "COMMUNITY" if args.community else "SECURE",
        "containerDiskInGb": args.disk,
        "volumeInGb": 0,
        "ports": ["22/tcp"],
        "supportPublicIp": True,
        "env": {"PUBLIC_KEY": pub},
        "dockerEntrypoint": ["bash", "-c"],
        "dockerStartCmd": [BOOT],
    }
    def create():
        # RunPod returns 500 when no machine of that type is free; retry, then fall back to Community Cloud.
        for attempt, cloud in enumerate([body["cloudType"]] * 3 + ["COMMUNITY"] * 3):
            body["cloudType"] = cloud
            try:
                return api("POST", "/pods", body)
            except urllib.error.HTTPError as e:
                print(f"create failed ({cloud}, attempt {attempt + 1}): {e.code} {e.read()[:300]!r}", flush=True)
                time.sleep(20)
        sys.exit("could not create a pod")

    # Some machines never get a public IP / SSH: drop them quickly and rent another.
    for boot_try in range(3):
        pod = create()
        pod_id = pod["id"]
        print(f"pod {pod_id} created, ${pod.get('costPerHr')}/hr on {args.gpu}", flush=True)
        t_start = time.time()
        try:
            pod, ip, port = wait_for_ssh(pod_id)
            break
        except TimeoutError as e:
            print(f"pod {pod_id} unusable ({e}); terminating and retrying", flush=True)
            api("DELETE", f"/pods/{pod_id}")
    else:
        sys.exit("no usable pod after 3 tries")
    try:
        ssh = ssh_base(ip, port)
        scp = ["scp", "-i", SSH_KEY, "-P", str(port), "-o", "StrictHostKeyChecking=no",
               "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
        code = pack_code()
        sh(scp + [code, f"root@{ip}:/workspace/_code.tar.gz"])
        sh(ssh + ["mkdir -p /workspace/code && tar -xzf /workspace/_code.tar.gz -C /workspace/code"])
        os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
        for key in args.models:
            # nohup so a dropped SSH connection doesn't kill the job; then poll for the DONE marker.
            envs = " ".join(shlex.quote(e) for e in args.env)
            sh(ssh + [f"{('env ' + envs) if envs else ''} nohup bash /workspace/code/runpod/job.sh {key} > /workspace/nohup_{key}.log 2>&1 &"])
            failed = False
            while True:
                r = subprocess.run(ssh + [f"test -f /workspace/DONE_{key} && echo done; "
                                          f"pgrep -f '[j]ob.sh {key}' >/dev/null || echo dead; "
                                          f"tail -1 /workspace/job_{key}.log 2>/dev/null"],
                                   capture_output=True, text=True)
                out = r.stdout.strip()
                print(f"[{key} {time.time() - t_start:.0f}s] {out.splitlines()[-1] if out else ''}", flush=True)
                if "done" in out.splitlines()[:1] or out.startswith("done"):
                    break
                if out.startswith("dead"):
                    for log in (f"job_{key}.log", f"vllm_{key}.log", f"nohup_{key}.log"):
                        sh(scp + [f"root@{ip}:/workspace/{log}", os.path.join(ROOT, "results", f"failed_{log}")], check=False)
                    print(f"!! job {key} died; logs in results/failed_*_{key}.log — moving to next model", flush=True)
                    failed = True
                    break
                time.sleep(30)
            if failed:
                continue
            tgz = os.path.join(ROOT, "results", f"out_{key}.tar.gz")
            sh(scp + [f"root@{ip}:/workspace/out_{key}.tar.gz", tgz])
            with tarfile.open(tgz) as t:
                t.extractall(os.path.join(ROOT, "results"), filter="data")
            with open(os.path.join(ROOT, "results", key, "_pod.json"), "w") as f:
                json.dump({"pod_id": pod_id, "gpu": args.gpu, "cost_per_hr": pod.get("costPerHr"),
                           "cloud": body["cloudType"]}, f, indent=2)
    finally:
        if args.keep:
            print(f"pod {pod_id} left running (--keep). Terminate it yourself!")
        else:
            api("DELETE", f"/pods/{pod_id}")
            hrs = (time.time() - t_start) / 3600
            print(f"pod {pod_id} terminated after {hrs:.2f} h (~${hrs * float(pod.get('costPerHr') or 0):.2f})")


if __name__ == "__main__":
    sys.exit(main())
