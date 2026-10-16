"""
Shared toolchain config + shell runner for Layer 1.

bcftools and Java (for PharmCAT) live inside WSL2 Ubuntu, since bcftools has no native
Windows build. Their locations differ per machine, so they are read from the environment
(.env at the repo root) instead of being hardcoded:

  BCFTOOLS_BIN   path to bcftools inside WSL/Linux    (default: "bcftools" on PATH)
  JAVA_BIN       path to java (17+) inside WSL/Linux  (default: "java" on PATH)
  PHARMCAT_JAR   path to pharmcat-<ver>-all.jar       (default: tools/pharmcat/pharmcat-3.4.0-all.jar)
  WSL_DISTRO     WSL distribution to use on Windows   (default: "Ubuntu")
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BCFTOOLS_BIN = os.environ.get("BCFTOOLS_BIN", "bcftools")
JAVA_BIN = os.environ.get("JAVA_BIN", "java")
PHARMCAT_JAR = ROOT / os.environ.get("PHARMCAT_JAR", "tools/pharmcat/pharmcat-3.4.0-all.jar")  # absolute paths override ROOT
WSL_DISTRO = os.environ.get("WSL_DISTRO", "Ubuntu")


def to_posix_path(path: Path) -> str:
    """Convert a Windows path (D:\\x) to its WSL mount (/mnt/d/x); Linux paths pass through."""
    p = str(path.resolve()).replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":
        return f"/mnt/{p[0].lower()}{p[2:]}"
    return p


def run_bash(script: str, label: str = "Command") -> str:
    """Run a bash script natively on Linux/WSL, or inside WSL when called from Windows.
    Raises RuntimeError with stderr on a non-zero exit; returns stdout."""
    script = script.replace("\r\n", "\n").replace("\r", "\n")
    cmd = ["wsl", "-d", WSL_DISTRO, "--", "bash"] if sys.platform == "win32" else ["bash"]
    result = subprocess.run(cmd, input=script.encode("utf-8"), capture_output=True)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed (code {result.returncode}):\n{script}\n\nSTDERR:\n{stderr}\nSTDOUT:\n{stdout}")
    return stdout
