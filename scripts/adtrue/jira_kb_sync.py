#!/usr/bin/env python3
"""Sync Jira Cloud issues into an AdTrue KB (WeKnora) knowledge base.

One markdown document per issue. Incremental: keeps a state file mapping
issue key -> (updated timestamp, knowledge id); changed issues are deleted
and re-uploaded, unchanged ones are skipped.

Config comes from a KEY=VALUE env file (default /opt/weknora-jira-sync/config.env):
    JIRA_BASE_URL=https://<site>.atlassian.net
    JIRA_EMAIL=<atlassian account email>
    JIRA_API_TOKEN=<token from id.atlassian.com/manage-profile/security/api-tokens>
    JIRA_JQL=project in (ADT) ORDER BY updated DESC   # optional; default: all issues
    WEKNORA_BASE_URL=https://kb.adtrue.io/api/v1
    WEKNORA_API_KEY=<scoped API key with knowledge write on the target KB>
    KB_ID=<knowledge base id>

Usage: jira_kb_sync.py [--config /path/config.env] [--dry-run]
Exits 0 with a notice (no error) while required config values are missing,
so the cron entry can be installed before credentials are filled in.
"""

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_CONFIG = "/opt/weknora-jira-sync/config.env"
REQUIRED = ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "WEKNORA_API_KEY", "KB_ID"]
PAGE_SIZE = 50
TIMEOUT = 60


def load_config(path):
    cfg = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
    cfg.setdefault("WEKNORA_BASE_URL", "https://kb.adtrue.io/api/v1")
    cfg.setdefault("JIRA_JQL", "updated >= \"2015-01-01\" ORDER BY updated DESC")
    return cfg


def http(method, url, headers=None, data=None, ok=(200, 201)):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jira_get(cfg, path, params):
    auth = base64.b64encode(
        ("%s:%s" % (cfg["JIRA_EMAIL"], cfg["JIRA_API_TOKEN"])).encode()
    ).decode()
    url = cfg["JIRA_BASE_URL"].rstrip("/") + path + "?" + urllib.parse.urlencode(params)
    status, body = http("GET", url, {"Authorization": "Basic " + auth, "Accept": "application/json"})
    if status != 200:
        raise RuntimeError("Jira GET %s -> HTTP %s: %s" % (path, status, body[:200]))
    return json.loads(body)


def adf_text(node, out):
    """Extract plain text from an Atlassian Document Format tree."""
    if node is None:
        return
    if isinstance(node, list):
        for n in node:
            adf_text(n, out)
        return
    t = node.get("type")
    if t == "text":
        out.append(node.get("text", ""))
    if t in ("paragraph", "heading", "listItem", "blockquote", "codeBlock"):
        adf_text(node.get("content"), out)
        out.append("\n")
    else:
        adf_text(node.get("content"), out)


def issue_markdown(cfg, issue):
    f = issue["fields"]
    key = issue["key"]
    desc = []
    adf_text(f.get("description"), desc)
    comments = []
    for c in (f.get("comment") or {}).get("comments", []):
        body = []
        adf_text(c.get("body"), body)
        author = (c.get("author") or {}).get("displayName", "?")
        comments.append("- **%s** (%s): %s" % (author, c.get("created", "")[:10], "".join(body).strip()))
    lines = [
        "# [%s] %s" % (key, f.get("summary", "")),
        "",
        "- **Status**: %s" % ((f.get("status") or {}).get("name", "")),
        "- **Type**: %s" % ((f.get("issuetype") or {}).get("name", "")),
        "- **Priority**: %s" % ((f.get("priority") or {}).get("name", "")),
        "- **Assignee**: %s" % ((f.get("assignee") or {}).get("displayName", "unassigned")),
        "- **Reporter**: %s" % ((f.get("reporter") or {}).get("displayName", "")),
        "- **Labels**: %s" % ", ".join(f.get("labels") or []),
        "- **Updated**: %s" % f.get("updated", ""),
        "- **Link**: %s/browse/%s" % (cfg["JIRA_BASE_URL"].rstrip("/"), key),
        "",
        "## Description",
        "",
        "".join(desc).strip() or "(no description)",
    ]
    if comments:
        lines += ["", "## Comments", ""] + comments
    return "\n".join(lines)


def weknora_upload(cfg, filename, content):
    boundary = uuid.uuid4().hex
    body = (
        "--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
        "Content-Type: text/markdown\r\n\r\n" % (boundary, filename)
    ).encode() + content.encode() + ("\r\n--%s--\r\n" % boundary).encode()
    url = "%s/knowledge-bases/%s/knowledge/file" % (cfg["WEKNORA_BASE_URL"].rstrip("/"), cfg["KB_ID"])
    status, resp = http(
        "POST", url,
        {"X-API-Key": cfg["WEKNORA_API_KEY"], "Content-Type": "multipart/form-data; boundary=" + boundary},
        body,
    )
    if status not in (200, 201):
        raise RuntimeError("WeKnora upload %s -> HTTP %s: %s" % (filename, status, resp[:300]))
    data = json.loads(resp)
    return (data.get("data") or {}).get("id", "")


def weknora_delete(cfg, knowledge_id):
    url = "%s/knowledge/%s" % (cfg["WEKNORA_BASE_URL"].rstrip("/"), knowledge_id)
    http("DELETE", url, {"X-API-Key": cfg["WEKNORA_API_KEY"]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    missing = [k for k in REQUIRED if not cfg.get(k) or cfg[k].startswith("<")]
    if missing:
        print("jira_kb_sync: config incomplete (missing %s) — nothing to do" % ", ".join(missing))
        return 0

    state_path = os.path.join(os.path.dirname(args.config), "state.json")
    state = {}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)

    def save_state():
        tmp = state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, state_path)

    next_token, synced, skipped = None, 0, 0
    while True:
        params = {
            "jql": cfg["JIRA_JQL"],
            "maxResults": PAGE_SIZE,
            "fields": "summary,description,status,issuetype,priority,assignee,reporter,labels,updated,comment",
        }
        if next_token:
            params["nextPageToken"] = next_token
        # /search/jql is the replacement for the retired /rest/api/3/search
        page = jira_get(cfg, "/rest/api/3/search/jql", params)
        issues = page.get("issues", [])
        for issue in issues:
            key = issue["key"]
            updated = issue["fields"].get("updated", "")
            prev = state.get(key, {})
            if prev.get("updated") == updated:
                skipped += 1
                continue
            md = issue_markdown(cfg, issue)
            if args.dry_run:
                print("would sync %s (%d bytes)" % (key, len(md)))
                continue
            if prev.get("knowledge_id"):
                weknora_delete(cfg, prev["knowledge_id"])
            kid = weknora_upload(cfg, key + ".md", md)
            state[key] = {"updated": updated, "knowledge_id": kid}
            synced += 1
            # Persist after every upload so an interrupted run never re-uploads
            # (duplicates) what already made it into the KB.
            save_state()
            time.sleep(0.3)  # be gentle with ingestion pipeline
        next_token = page.get("nextPageToken")
        if not next_token or not issues:
            break

    if not args.dry_run:
        save_state()
    print("jira_kb_sync: %d synced, %d unchanged, %d total known" % (synced, skipped, len(state)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
