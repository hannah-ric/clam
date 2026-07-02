"""
diagnose_network.py
===================

CLIMADA reported "no internet connection," but the data server is up. That means
something on the corporate network is blocking the HTTPS connection. This script
finds out which of three things it is, and for the most common one (your company
intercepting TLS with its own certificate) it builds the fix for you.

Run:  python diagnose_network.py
"""

import os
import shutil
import subprocess
import sys

API = "https://climada.ethz.ch/data-api/v1/dataset/?data_type=tropical_cyclone&limit=1"
CTRL = "https://pypi.org/simple/"


def probe(label, url, **kw):
    import requests
    try:
        r = requests.get(url, timeout=25, **kw)
        print(f"  {label:30} -> HTTP {r.status_code}")
        return True
    except Exception as exc:
        print(f"  {label:30} -> {type(exc).__name__}: {str(exc)[:160]}")
        return False


def build_ca_bundle():
    """Combine the public CA bundle with your Mac's system/keychain certificates
    (which include the corporate root CA that IT installed). Returns the path."""
    import certifi
    out = os.path.expanduser("~/rtv-cacert.pem")
    shutil.copy(certifi.where(), out)
    keychains = [
        "/Library/Keychains/System.keychain",
        "/System/Library/Keychains/SystemRootCertificates.keychain",
    ]
    added = 0
    with open(out, "ab") as fh:
        for kc in keychains:
            try:
                res = subprocess.run(
                    ["security", "find-certificate", "-a", "-p", kc],
                    capture_output=True, text=True, timeout=40,
                )
                if res.stdout:
                    fh.write(b"\n" + res.stdout.encode())
                    added += res.stdout.count("BEGIN CERTIFICATE")
            except Exception as exc:
                print("   (could not read", kc, ":", exc, ")")
    print(f"  built {out}  (added {added} system/keychain certificates)")
    return out


def main():
    print("python:", sys.executable)
    try:
        import requests, certifi
        print("requests:", requests.__version__, "| certifi:", certifi.where())
    except Exception as exc:
        print("cannot import requests/certifi:", exc)
        return 1

    proxies = {k: v for k, v in os.environ.items() if "proxy" in k.lower()}
    print("proxy env vars:", proxies or "none set")

    print("\nTESTS")
    ctrl_def = probe("control  pypi.org (default)", CTRL)
    cli_def = probe("climada  data API (default)", API)
    cli_nov = probe("climada  data API (no verify)", API, verify=False)

    print("\nVERDICT")
    if cli_def:
        print("  Connection is fine now. Re-run: python check_climada.py")
        return 0

    if cli_nov:
        print("  Cause: corporate TLS interception. Python does not trust your")
        print("  company's root certificate, so the secure connection is rejected.")
        print("  Building a certificate bundle that includes it...\n")
        bundle = build_ca_bundle()
        print("\n  Verifying the fix with that bundle...")
        ok = probe("climada  data API (corp bundle)", API, verify=bundle)
        print()
        if ok:
            print("  FIXED. Now tell every tool in this terminal to use that bundle,")
            print("  then re-run the check. Paste these three lines:\n")
            print('    export REQUESTS_CA_BUNDLE="$HOME/rtv-cacert.pem"')
            print('    export SSL_CERT_FILE="$HOME/rtv-cacert.pem"')
            print("    python check_climada.py\n")
            print("  To make it permanent, add the two export lines to ~/.zshrc.")
        else:
            print("  The bundle did not resolve it. Send this whole output back.")
        return 0

    if ctrl_def:
        print("  Cause: climada.ethz.ch is reachable nowhere from here, but pypi is.")
        print("  The host itself is being blocked by network policy.")
        print("  Options: ask IT to allowlist climada.ethz.ch, or run the download")
        print("  off the corporate network (home wifi, or VPN split-tunnel disabled).")
        return 0

    print("  Cause: all HTTPS is failing, which points to a required proxy or")
    print("  no outbound access for this Python. If your company uses a proxy,")
    print("  set it in this terminal, for example:")
    print('    export HTTPS_PROXY="http://YOUR.PROXY.HOST:PORT"')
    print('    export HTTP_PROXY="http://YOUR.PROXY.HOST:PORT"')
    print("  then re-run. Get the proxy address from IT or from System Settings >")
    print("  Network > Details > Proxies. If it is a .pac auto-config, send it back.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
