import asyncio
import subprocess


def cmdline(cmd):
    try:
        output = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
        return output
    except subprocess.CalledProcessError as e:
        return e.output.decode('utf-8').strip() if e.output else f"Command failed with return code {e.returncode}"

