#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
本机 git 走 HTTPS 会被代理挡下（CONNECT tunnel failed 502），但 api.github.com 是通的，
所以改用 GitHub REST API（Git Data API）直接把本地 HEAD 提交上去。

用法：
    python scripts/push_via_api.py            # 推送最近一次 commit
    python scripts/push_via_api.py HEAD~1     # 推送最近两次（按提交顺序）

需要环境变量 GITHUB_TOKEN（或脚本同目录的 .token 文件）。
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

OWNER = "DQ-HollyLee"
REPO = "icao900-asmr"
BRANCH = "main"
API = "https://api.github.com"


def token():
    t = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if t:
        return t.strip()
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".token")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().strip()
    raise SystemExit("缺少 GITHUB_TOKEN")


def gh(method, path, body=None, tok=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise SystemExit("HTTP %d %s\n%s" % (e.code, path, e.read().decode("utf-8", "ignore")[:600]))


def git(*args):
    return subprocess.run(["git"] + list(args), capture_output=True, text=True,
                          cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                          ).stdout.strip()


def main():
    base_rev = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    tok = token()

    # 要推送的 commit 列表（从旧到新）
    if base_rev.startswith("HEAD~"):
        n = int(base_rev.split("~")[1] or 1)
        revs = [git("rev-parse", "HEAD~%d" % (n - i - 1)) for i in range(n)]
    else:
        revs = [git("rev-parse", "HEAD")]

    remote = gh("GET", "/repos/%s/%s/git/ref/heads/%s" % (OWNER, REPO, BRANCH), tok=tok)
    parent = remote["object"]["sha"]
    print("远端 %s 当前 %s" % (BRANCH, parent[:8]))

    for rev in revs:
        msg = git("log", "-1", "--format=%B", rev)
        files = [l for l in git("show", "--name-only", "--format=", rev).splitlines() if l.strip()]
        print("\n提交 %s：%s（%d 个文件）" % (rev[:8], msg.splitlines()[0][:60], len(files)))

        tree_items = []
        for f in files:
            content = subprocess.run(["git", "show", "%s:%s" % (rev, f)],
                                     capture_output=True,
                                     cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                                     ).stdout
            if not content and b"" == content:
                tree_items.append({"path": f, "mode": "100644", "type": "blob", "sha": None})
                continue
            b = gh("POST", "/repos/%s/%s/git/blobs" % (OWNER, REPO),
                   {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
                   tok=tok)
            mode = "100755" if (git("ls-files", "-s", f).startswith("100755")) else "100644"
            tree_items.append({"path": f, "mode": mode, "type": "blob", "sha": b["sha"]})
            print("   %-46s %8d B" % (f, len(content)))

        tree = gh("POST", "/repos/%s/%s/git/trees" % (OWNER, REPO),
                  {"base_tree": parent, "tree": tree_items}, tok=tok)
        commit = gh("POST", "/repos/%s/%s/git/commits" % (OWNER, REPO),
                    {"message": msg, "tree": tree["sha"], "parents": [parent]}, tok=tok)
        gh("PATCH", "/repos/%s/%s/git/refs/heads/%s" % (OWNER, REPO, BRANCH),
           {"sha": commit["sha"]}, tok=tok)
        parent = commit["sha"]
        print("   → %s" % commit["sha"][:8])

    print("\n完成：https://github.com/%s/%s/commits/%s" % (OWNER, REPO, BRANCH))


if __name__ == "__main__":
    main()
