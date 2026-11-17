# CAMserv — Phase 25.1-B Cross-Platform Worker Termination & Process Isolation Report

**Document ID:** QUAL-P25.1B-WORKER-2026-016  
**Project:** CAMserv — Advanced Security Intelligence Platform  
**Target Release:** `0.10.0-rc7`  
**Phase:** 25.1-B — Stage A  
**Date:** November 17, 2026  
**Auditor Roles:** Principal Systems Architect, Operating Systems Kernel Engineer & Reliability Auditor  
**Primary Host:** Windows 11 Enterprise x86_64 Build 26300  
**Secondary Platform Target:** Debian/Linux 12 (bookworm) x86_64  

---

## 1. Architectural Overview & Critical Integrity Invariant

In surveillance video management systems, background worker processes and threads handle high-throughput operations: RTSP elementary stream decoding, neural inference pipeline execution, and filesystem write flushing.

When a worker hangs, stalls, or crashes:
1. **The Anti-Duplicate Lease Fencing Invariant:** Under NO circumstances may a channel lease be released or reassigned to a new worker until the previous worker is **independently confirmed terminated**. Releasing a lease while the old process is still alive leads to multiple processes writing to the same segment file, corrupting MP4 container atoms and creating forensic evidence destruction.
2. **IPC Resource Reconciliation Invariant:** Terminated worker processes often leave parent queues and pipes locked or full. The supervisor must sanitize all registered IPC resources (`reconcile_ipc()`) to prevent deadlock in the supervisor thread.
3. **Cross-Platform Asymmetry Invariant:** Windows and POSIX/Linux handle process signals and handle reclamation with fundamentally different semantics. Software must truthfully differentiate what was physically executed on the current Windows host versus what was simulated or mocked for Linux.

---

## 2. Windows 11 Implementation & Execution

### 2.1 Process Termination & Confirmation Mechanics
On Windows systems, POSIX signals (`SIGTERM`, `SIGKILL`) do not natively exist. Attempting to access `signal.SIGKILL` raises `AttributeError: module 'signal' has no attribute 'SIGKILL'`.

The Windows implementation in [src/camserv/platform/stability.py](file:///c:/Users/MPront/Documents/CAMserv/src/camserv/platform/stability.py) operates as follows:

```python
# Process isolation path: enforceable termination
if self.worker_process is not None:
    proc = self.worker_process
    try:
        # 1. Graceful attempt via terminate()
        if not force:
            if hasattr(proc, "terminate"):
                proc.terminate()
            if hasattr(proc, "join"):
                proc.join(timeout_sec)

        # 2. Forced escalation if process is still alive or force=True
        is_alive = proc.is_alive() if hasattr(proc, "is_alive") else False
        if is_alive or force:
            if hasattr(proc, "kill"):
                proc.kill()  # Invokes Win32 TerminateProcess
            elif hasattr(proc, "terminate"):
                proc.terminate()
            if hasattr(proc, "join"):
                proc.join(timeout_sec)
            is_alive = proc.is_alive() if hasattr(proc, "is_alive") else False

        # 3. Independent exit confirmation
        if not is_alive:
            self.termination_forced = force
            self.termination_confirmed = True
            self.termination_unconfirmed = False
            self.state = WorkerLifecycleState.TERMINATED
            self.is_alive = False
            self.reconcile_ipc()
            self.revoke_channel_lease()
            return True
        else:
            # Process refused to terminate within timeout
            self.termination_confirmed = False
            self.termination_unconfirmed = True
            self.state = WorkerLifecycleState.TERMINATION_UNCONFIRMED
            return False
```

### 2.2 Win32 Handle Reaping & Zombie Prevention
On Windows:
- Win32 processes terminate immediately upon `TerminateProcess` (`proc.kill()`).
- The Python `multiprocessing.Process` object manages the underlying Win32 Process Handle.
- Calling `proc.join(timeout_sec)` waits on `WaitForSingleObject` for the process handle to enter the signaled state.
- `proc.is_alive()` polls the exit code via `GetExitCodeProcess`. If the exit code is `STILL_ACTIVE` (259), it returns `True`. Only when the exit code differs from `STILL_ACTIVE` does it return `False`.
- Channel leases are revoked **only and strictly after** `proc.is_alive()` returns `False`.

### 2.3 IPC Resource Reconciliation (`reconcile_ipc()`)
When a child process terminates abruptly, any `multiprocessing.Queue` or `Pipe` in use can cause the parent thread to hang when attempting to join feeder threads or close pipes.

`WorkerCrashSupervisor.reconcile_ipc()` resolves this:
```python
def reconcile_ipc(self) -> None:
    for res in self.ipc_resources:
        try:
            if hasattr(res, "close") and hasattr(res, "cancel_join_thread"):
                res.close()
                res.cancel_join_thread()
            elif hasattr(res, "close"):
                res.close()
        except Exception as exc:
            logger.warning("worker_supervisor.ipc_reconcile_warning", resource=str(res), error=str(exc))
    self.ipc_resources.clear()
```

---

## 3. POSIX/Linux Design & Escalation Semantics

### 3.1 Signal Escalation Protocol
On Linux systems:
1. **Graceful Stage:** Send `SIGTERM` to the process group (`os.killpg(os.getpgid(pid), signal.SIGTERM)` or `proc.terminate()`).
2. **Bounded Grace Period:** Await process termination with bounded timeout (e.g. 500ms to 2.0s).
3. **Forced Stage:** If process remains alive, escalate to `SIGKILL` (`proc.kill()`).
4. **Reaping & Zombie Prevention:** Execute `proc.join(timeout_sec)` or `os.waitpid(pid, 0)` to harvest the child process exit status from the kernel table, preventing accumulated zombie processes (`<defunct>`).

### 3.2 Evidence Classification & Truthfulness
Because the physical host for this audit is Windows 11 Enterprise, POSIX signal mechanics were qualified using mocks and unit simulations.
* **Windows Execution:** Tagged `ACTUALLY_EXECUTED_ON_WINDOWS`.
* **POSIX Escalation Logic:** Tagged `MOCKED` / `SOFTWARE_INTEGRATION_TESTED`.
* **Physical Linux Hardware Qualification:** Tagged **`NOT EXECUTED`**.

---

## 4. Test Verification Matrix & Evidence Classification

| Test Case | Description | Evidence Classification | Status |
| :--- | :--- | :--- | :---: |
| `test_windows_cooperative_cancellation_and_token_checkpoints` | Cooperative cancellation token checkpoints, clean worker stop, lease revocation | `ACTUALLY_EXECUTED_ON_WINDOWS` | **PASS** |
| `test_windows_unresponsive_worker_timeout_guard` | Unresponsive worker ignores cancellation; lease retained; `TERMINATION_UNCONFIRMED` | `ACTUALLY_EXECUTED_ON_WINDOWS` | **PASS** |
| `test_windows_process_forced_termination` | Forced process kill via `proc.kill()`, `is_alive()` confirmation, IPC cleanup | `ACTUALLY_EXECUTED_ON_WINDOWS` | **PASS** |
| `test_windows_process_exit_confirmation_is_alive_refusal` | Process refuses kill; supervisor retains channel lease, protecting channel | `ACTUALLY_EXECUTED_ON_WINDOWS` | **PASS** |
| `test_windows_ipc_resource_reconciliation` | Sanitation of queues and pipes via `reconcile_ipc()` preventing supervisor deadlock | `ACTUALLY_EXECUTED_ON_WINDOWS` | **PASS** |
| `test_channel_lease_retention_before_exit_confirmation` | Anti-duplicate worker fencing: concurrent worker acquisition blocked while old worker alive | `ACTUALLY_EXECUTED_ON_WINDOWS` | **PASS** |
| `test_unexpected_worker_crash_handling_and_backoff` | Crash recording, backoff calculation, and fencing after exceeding restart limit | `ACTUALLY_EXECUTED_ON_WINDOWS` | **PASS** |
| `test_partial_segment_recovery_after_process_kill` | In-flight `.part` quarantine and rename to `.recovered_partial.mp4` without data loss | `ACTUALLY_EXECUTED_ON_WINDOWS` | **PASS** |
| `test_posix_sigterm_sigkill_escalation_mocked` | POSIX SIGTERM -> SIGKILL escalation simulation with graceful exit confirmation | `MOCKED / SOFTWARE_INTEGRATION_TESTED` | **PASS** |

---

## 5. Qualification Verdict & Operational Boundary

* **Windows 11 Platform:** **PASS** (Fully verified against native Win32 runtime).
* **Linux Platform:** **CONDITIONAL PASS** (Software architecture verified; physical execution on Linux target host pending on-target qualification).
