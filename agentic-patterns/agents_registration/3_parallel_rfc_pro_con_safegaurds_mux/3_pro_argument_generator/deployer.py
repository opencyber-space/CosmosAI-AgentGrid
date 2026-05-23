#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from typing import Any, Dict

import requests

try:
    import yaml 
except ImportError:
    yaml = None


def load_kubeconfig(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    if not os.path.isfile(path):
        raise FileNotFoundError(f"kubeconfig file not found: {path}")
    text = open(path, "r", encoding="utf-8").read()
    if yaml is not None:
        try:
            return yaml.safe_load(text) or {}
        except Exception:
            pass
    try:
        return json.loads(text)
    except Exception as e:
        raise ValueError(f"kubeconfig must be YAML or JSON: {e}")


def request_json(
    method: str,
    url: str,
    payload: Dict[str, Any],
    token: str = None,
    timeout: int = 60,
) -> requests.Response:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    method = method.upper()
    if method == "POST":
        return requests.post(url, headers=headers, json=payload, timeout=timeout)
    elif method == "DELETE":
        # DELETE with JSON body is supported by requests (server reads request body)
        return requests.delete(url, headers=headers, json=payload, timeout=timeout)
    else:
        raise ValueError(f"Unsupported method: {method}")


def build_create_payload(args) -> Dict[str, Any]:
    return {
        "kubeconfig": load_kubeconfig(args.kubeconfig),
        "deployer_id": str(args.deployer_id),
        "deployer_name": str(args.deployer_name),
        "deployer_cluster_id": str(args.deployer_cluster_id),
        "deployer_public_ip": str(args.deployer_public_ip)
    }


def build_delete_payload(args) -> Dict[str, Any]:
    # API requires kubeconfig in body for DELETE
    return {
        "kubeconfig": load_kubeconfig(args.kubeconfig),
    }


def main():
    parser = argparse.ArgumentParser(description="Test create/delete Agent Deployer APIs")
    parser.add_argument("--base-url", default="http://localhost:5000", help="Base server URL (no trailing slash)")
    parser.add_argument("--token", help="Bearer token (optional)")
    parser.add_argument("--dry-run", action="store_true", help="Print payload and exit without sending")

    sub = parser.add_subparsers(dest="action", required=True)

    # create
    p_create = sub.add_parser("create", help="POST /api/agent-deployers")
    p_create.add_argument("--kubeconfig", required=True, help="Path to kubeconfig (YAML or JSON)")
    p_create.add_argument("--deployer-id", default=f"dep-{int(time.time())}", help="Deployer ID")
    p_create.add_argument("--deployer-name", default="AgentsDeployer", help="Deployer name")
    p_create.add_argument("--deployer-cluster-id", default="cluster-001", help="Cluster ID")
    p_create.add_argument("--deployer-public-ip", default="", help="public IP of the cluster")

    # delete
    p_delete = sub.add_parser("delete", help="DELETE /api/agent-deployers/<deployer_id>")
    p_delete.add_argument("--deployer-id", required=True, help="Deployer ID to delete")
    p_delete.add_argument("--kubeconfig", required=True, help="Path to kubeconfig (YAML or JSON)")

    args = parser.parse_args()

    if args.action == "create":
        payload = build_create_payload(args)
        url = f"{args.base_url.rstrip('/')}/api/agent-deployers"
        method = "POST"
    else:  # delete
        payload = build_delete_payload(args)
        url = f"{args.base_url.rstrip('/')}/api/agent-deployers/{args.deployer_id}"
        method = "DELETE"

    # print request with kubeconfig redacted
    printable = (payload or {}).copy()
    if "kubeconfig" in printable:
        printable["kubeconfig"] = "<redacted dict>"
    print("== Request ==")
    print(f"{method} {url}")
    if payload is not None:
        print(json.dumps(printable, indent=2))
    print()

    if args.dry_run:
        print("[dry-run] not sending request")
        sys.exit(0)

    try:
        resp = request_json(method, url, payload, token=args.token)
    except requests.RequestException as e:
        print(f"[error] request failed: {e}", file=sys.stderr)
        sys.exit(3)

    print(f"== Response ({resp.status_code}) ==")
    ctype = resp.headers.get("Content-Type", "")
    if "application/json" in ctype:
        try:
            print(json.dumps(resp.json(), indent=2))
        except Exception:
            print(resp.text)
    else:
        print(resp.text)

    # Non-2xx → fail (useful in CI)
    if not (200 <= resp.status_code < 300):
        sys.exit(4)


if __name__ == "__main__":
    main()
