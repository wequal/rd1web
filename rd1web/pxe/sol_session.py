import os
import pty
import subprocess
import fcntl
import select
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

class SOLSession:
    """Manage an ipmitool SOL (Serial-over-LAN) session using a pseudo-terminal.

    This class is **process-agnostic** and can therefore be reused by both
    synchronous Django views and asynchronous Channels consumers (ASGI).
    """

    def __init__(self, folder_name: str, bmc_ip: str, bmc_user: str, bmc_pwd: str) -> None:
        self.folder_name = folder_name
        self.bmc_ip = bmc_ip
        self.bmc_user = bmc_user
        self.bmc_pwd = bmc_pwd

        self.process: Optional[subprocess.Popen] = None
        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.running: bool = False
        # Optional attribute for views that attach WebSocket object
        self.websocket = None

    # ---------------------------------------------------------------------
    # Public helpers
    # ---------------------------------------------------------------------
    def start(self) -> bool:
        """Spawn *ipmitool* in SOL mode. Returns *True* if it started OK."""
        try:
            # Create a new pseudo-terminal pair
            self.master_fd, self.slave_fd = pty.openpty()

            # First, ensure any existing SOL sessions are properly terminated
            deactivate_cmd = [
                "ipmitool", "-I", "lanplus",
                "-C", "3",  # Ensure deactivation also uses cipher suite 3
                "-H", self.bmc_ip,
                "-U", self.bmc_user,
                "-P", self.bmc_pwd,
                "sol", "deactivate",
            ]
            
            try:
                # Run deactivate command with timeout
                result = subprocess.run(deactivate_cmd, capture_output=True, timeout=10, text=True)
                logger.info(f"SOL deactivate result for {self.folder_name}: {result.stdout} {result.stderr}")
            except subprocess.TimeoutExpired:
                logger.warning(f"SOL deactivate timeout for {self.folder_name}")
            except Exception as e:
                logger.warning(f"SOL deactivate failed for {self.folder_name}: {e}")

            # Now start the SOL session with explicit cipher suite
            cmd = [
                "ipmitool", "-I", "lanplus",
                "-C", "3",  # Explicitly use cipher suite 3 for IPMI v2.0
                "-H", self.bmc_ip,
                "-U", self.bmc_user,
                "-P", self.bmc_pwd,
                "sol", "activate",
            ]
            
            logger.info(f"Starting SOL session for {self.folder_name} with command: {' '.join(cmd)}")

            self.process = subprocess.Popen(
                cmd,
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                preexec_fn=os.setsid,
            )

            # Parent no longer needs the *slave* side.
            os.close(self.slave_fd)
            self.slave_fd = None

            # Make master non-blocking so we can poll without hanging.
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, os.O_NONBLOCK)

            self.running = True
            logger.info("Started SOL session for %s (PID=%s)", self.folder_name, self.process.pid)
            return True
        except Exception as e:
            logger.exception("Failed to start SOL process for %s: %s", self.folder_name, str(e))
            self.cleanup()
            return False

    def read(self, size: int = 1024) -> Optional[str]:
        """Read *size* bytes of data if available, otherwise return *None*."""
        if not self.running or self.master_fd is None:
            return None
        try:
            ready, _, _ = select.select([self.master_fd], [], [], 0)
            if ready:
                data = os.read(self.master_fd, size)
                return data.decode("utf-8", errors="ignore")
        except (OSError, BlockingIOError):
            pass  # Nothing to read yet
        except Exception:
            logger.exception("Error reading from SOL")
        return None

    def write(self, data: str) -> bool:
        """Write data to the SOL session, returning *True* on success."""
        if not self.running or self.master_fd is None:
            return False
        try:
            os.write(self.master_fd, data.encode("utf-8"))
            return True
        except Exception:
            logger.exception("Error writing to SOL")
            return False

    async def drain_to(self, send_coroutine, poll_interval: float = 0.01):
        """Continuously read from SOL and forward to *send_coroutine*.

        Meant for ASGI/Channels consumers – pass in *self.channel_layer.send*
        or *WebSocket.send* etc.  Stops when *self.running* becomes *False*.
        """
        while self.running:
            out = self.read()
            if out:
                await send_coroutine(out)
            await asyncio.sleep(poll_interval)

    # ------------------------------------------------------------------
    # Cleanup helpers
    # ------------------------------------------------------------------
    def cleanup(self) -> None:
        """Terminate the ipmitool process and close file descriptors."""
        self.running = False

        # Try to exit SOL cleanly (~.) before killing.
        if self.master_fd and self.process and self.process.poll() is None:
            try:
                os.write(self.master_fd, b"~.")
            except Exception:
                pass

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            except Exception:
                logger.exception("Error terminating SOL process")
            finally:
                self.process = None

        for fd in (self.master_fd, self.slave_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
        self.master_fd = self.slave_fd = None

        logger.info("Cleaned up SOL session for %s", self.folder_name)

    # ------------------------------------------------------------------
    # Legacy aliases (for backward compatibility with existing modules)
    # ------------------------------------------------------------------

    # Older code used *start_sol_process* / *read_from_sol* / *write_to_sol*.
    # Keep thin wrappers so that refactoring does not break imports.

    def start_sol_process(self) -> bool:  # noqa: N802 (non-pep8 name kept for compat)
        return self.start()

    def read_from_sol(self, size: int = 1024) -> Optional[str]:  # noqa: N802
        return self.read(size)

    def write_to_sol(self, data: str) -> bool:  # noqa: N802
        return self.write(data) 