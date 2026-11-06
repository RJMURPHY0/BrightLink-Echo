# Each call here should be flagged by security/semgrep/brightlink.yml.
import subprocess, requests
requests.get("https://x", verify=False)
subprocess.run(["powershell", "-File", "x.ps1"])
