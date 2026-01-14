# =============================================================================
# SMART COLAB AGENT v2 - Lightweight MCP Server
# =============================================================================
# Inspired by doobidoo/mcp-memory-service patterns:
# - Timeout-aware execution with chunking
# - Progress reporting
# - Checkpointing for long operations
# - Lightweight dependencies (no heavy ML libs locally)
# =============================================================================

import os
import sys
import json
import time
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

import requests

# Try lightweight MCP import
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Installing mcp package...", file=sys.stderr)
    os.system(f"{sys.executable} -m pip install mcp")
    from mcp.server.fastmcp import FastMCP


# =============================================================================
# CONFIGURATION
# =============================================================================

COLAB_URL = os.environ.get("COLAB_URL", "Hard code the url if needed")
LOCAL_SAVE_DIR = os.environ.get("LOCAL_SAVE_DIR", str(Path.home() / "colab_results"))
CHECKPOINT_DIR = os.environ.get("CHECKPOINT_DIR", str(Path.home() / ".cache" / "colab_checkpoints"))

# Timeout settings (inspired by doobidoo's approach)
TIMEOUTS = {
    "quick": 30,      # Health checks, variable listing
    "normal": 120,    # Code execution, file ops
    "long": 300,      # Training, large downloads
    "max": 600        # Absolute maximum
}

# Ensure directories exist
Path(LOCAL_SAVE_DIR).mkdir(parents=True, exist_ok=True)
Path(CHECKPOINT_DIR).mkdir(parents=True, exist_ok=True)


# =============================================================================
# MCP SERVER
# =============================================================================

mcp = FastMCP("smart-colab-v2")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_checkpoint_path(operation: str) -> Path:
    """Get checkpoint file path for an operation"""
    return Path(CHECKPOINT_DIR) / f"{operation}_{datetime.now().strftime('%Y%m%d')}.json"


def save_checkpoint(operation: str, data: Dict[str, Any]) -> str:
    """Save checkpoint data"""
    path = get_checkpoint_path(operation)
    with open(path, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "data": data
        }, f, indent=2)
    return str(path)


def load_checkpoint(operation: str) -> Optional[Dict[str, Any]]:
    """Load checkpoint data if exists"""
    path = get_checkpoint_path(operation)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def make_request(method: str, endpoint: str, timeout: int = TIMEOUTS["normal"], **kwargs) -> Dict[str, Any]:
    """Make HTTP request to Colab with proper error handling"""
    url = f"{COLAB_URL}{endpoint}"

    try:
        if method == "GET":
            response = requests.get(url, timeout=timeout, **kwargs)
        else:
            response = requests.post(url, timeout=timeout, **kwargs)

        if response.status_code == 200:
            return {"success": True, "data": response.json()}
        else:
            return {"success": False, "error": f"HTTP {response.status_code}", "body": response.text[:500]}

    except requests.exceptions.Timeout:
        return {"success": False, "error": "TIMEOUT", "suggestion": f"Operation took longer than {timeout}s"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "CONNECTION_FAILED", "url": COLAB_URL}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# TOOL 1: Check Connection (Quick)
# =============================================================================
@mcp.tool()
def check_colab_connection() -> Dict[str, Any]:
    """
    Quick health check - is Colab alive?

    Timeout: 10 seconds (fast fail)
    Use: Before any operation to verify connection

    Returns:
        status: "connected" or "disconnected"
        uptime_minutes: How long Colab has been running
        memory_available_gb: Free RAM
    """
    result = make_request("GET", "/health", timeout=TIMEOUTS["quick"])

    if result["success"]:
        data = result["data"]
        data["status"] = "connected"
        data["colab_url"] = COLAB_URL
        return data
    else:
        return {
            "status": "disconnected",
            "error": result.get("error"),
            "colab_url": COLAB_URL,
            "suggestion": "Check if Colab notebook is running and ngrok URL is correct"
        }


# =============================================================================
# TOOL 2: Probe Environment (Quick)
# =============================================================================
@mcp.tool()
def probe_colab_environment() -> Dict[str, Any]:
    """
    Get Colab environment info - RAM, GPU, packages.

    ALWAYS CALL THIS FIRST before heavy operations.

    Timeout: 30 seconds

    Returns:
        compute: CPU cores, RAM total/available
        gpu: Available, name, memory
        packages: Installed versions
        limits: Recommended batch sizes, session time remaining
    """
    result = make_request("GET", "/probe", timeout=TIMEOUTS["quick"])

    if result["success"]:
        # Add recommendations based on resources
        data = result["data"]
        gpu = data.get("gpu", {})
        ram_gb = data.get("compute", {}).get("ram_available_gb", 0)

        recommendations = []
        if not gpu.get("available"):
            recommendations.append("No GPU - use classical ML only, avoid deep learning")
        if ram_gb < 4:
            recommendations.append(f"Low RAM ({ram_gb:.1f}GB) - sample datasets, use smaller batches")
        if data.get("limits", {}).get("estimated_session_minutes_remaining", 90) < 30:
            recommendations.append("Session ending soon - save checkpoints now!")

        data["recommendations"] = recommendations
        return data
    else:
        return result


# =============================================================================
# TOOL 3: Run Code - Short Operations (Normal timeout)
# =============================================================================
@mcp.tool()
def run_code_quick(code: str) -> Dict[str, Any]:
    """
    Execute Python code on Colab - for QUICK operations (<2 min).

    Use for:
    - Import statements
    - Data loading (small files)
    - Quick computations
    - Printing summaries

    Timeout: 120 seconds

    Args:
        code: Python code to execute (can be multi-line)

    Returns:
        success: True/False
        stdout: Printed output
        execution_time_sec: How long it took
        memory_after_gb: Available RAM after
    """
    result = make_request(
        "POST", "/execute",
        timeout=TIMEOUTS["normal"] + 30,  # Buffer for network
        json={"code": code, "timeout": TIMEOUTS["normal"]}
    )

    if result["success"]:
        return result["data"]
    else:
        return result


# =============================================================================
# TOOL 4: Run Code - Long Operations (Extended timeout)
# =============================================================================
@mcp.tool()
def run_code_long(code: str, checkpoint_name: str = "") -> Dict[str, Any]:
    """
    Execute Python code on Colab - for LONG operations (up to 10 min).

    Use for:
    - Training models
    - Processing large datasets
    - Batch feature extraction

    IMPORTANT: Include progress prints in your code!

    Timeout: 600 seconds (10 min)

    Args:
        code: Python code (should include print() for progress)
        checkpoint_name: Optional name to save result as checkpoint

    Returns:
        success: True/False
        stdout: All printed output
        execution_time_sec: Duration
        checkpoint_saved: Path if checkpointed
    """
    result = make_request(
        "POST", "/execute",
        timeout=TIMEOUTS["max"] + 60,
        json={"code": code, "timeout": TIMEOUTS["max"]}
    )

    response = result["data"] if result["success"] else result

    # Save checkpoint if requested
    if checkpoint_name and result["success"]:
        checkpoint_path = save_checkpoint(checkpoint_name, {
            "code": code[:500],  # First 500 chars of code
            "stdout": response.get("stdout", "")[:2000],  # First 2000 chars of output
            "execution_time": response.get("execution_time_sec"),
            "completed_at": datetime.now().isoformat()
        })
        response["checkpoint_saved"] = checkpoint_path

    return response


# =============================================================================
# TOOL 5: Run Code in Chunks (For very long operations)
# =============================================================================
@mcp.tool()
def run_chunked_operation(
    setup_code: str,
    loop_code: str,
    n_iterations: int,
    batch_size: int = 10,
    checkpoint_name: str = "chunked_op"
) -> Dict[str, Any]:
    """
    Run a long operation in chunks to avoid timeouts.

    Perfect for:
    - Processing 1000+ images
    - Training for many epochs
    - Batch predictions

    How it works:
    1. Runs setup_code once
    2. Runs loop_code for batch_size iterations
    3. Returns progress, can be resumed

    Args:
        setup_code: One-time setup (imports, data loading)
        loop_code: Code to run repeatedly (use {i} for iteration number)
        n_iterations: Total iterations needed
        batch_size: How many to do per call (default 10)
        checkpoint_name: Name for progress checkpoint

    Returns:
        completed: Iterations completed so far
        remaining: Iterations left
        output: Combined stdout from this batch
        can_continue: Whether more iterations remain

    Example:
        run_chunked_operation(
            setup_code="import os; files = os.listdir('/content/data')",
            loop_code="print(f'Processing {i}: {files[{i}]}')",
            n_iterations=100,
            batch_size=20
        )
    """
    # Load checkpoint to see where we left off
    checkpoint = load_checkpoint(checkpoint_name)
    start_idx = 0
    if checkpoint:
        start_idx = checkpoint.get("data", {}).get("completed", 0)

    end_idx = min(start_idx + batch_size, n_iterations)

    # Build the execution code
    if start_idx == 0:
        # First run: include setup
        full_code = f"""
{setup_code}

# Chunked execution: iterations {start_idx} to {end_idx-1}
for i in range({start_idx}, {end_idx}):
    {loop_code}

print(f"Completed iterations {start_idx} to {end_idx-1}")
"""
    else:
        # Resume: skip setup
        full_code = f"""
# Resuming chunked execution: iterations {start_idx} to {end_idx-1}
for i in range({start_idx}, {end_idx}):
    {loop_code}

print(f"Completed iterations {start_idx} to {end_idx-1}")
"""

    result = make_request(
        "POST", "/execute",
        timeout=TIMEOUTS["long"] + 30,
        json={"code": full_code, "timeout": TIMEOUTS["long"]}
    )

    # Save progress checkpoint
    save_checkpoint(checkpoint_name, {
        "completed": end_idx,
        "total": n_iterations,
        "last_batch_output": result.get("data", {}).get("stdout", "")[:1000] if result["success"] else ""
    })

    return {
        "completed": end_idx,
        "remaining": n_iterations - end_idx,
        "progress_pct": round(end_idx / n_iterations * 100, 1),
        "output": result.get("data", {}).get("stdout", "") if result["success"] else result.get("error"),
        "success": result["success"],
        "can_continue": end_idx < n_iterations,
        "next_command": f"run_chunked_operation(..., checkpoint_name='{checkpoint_name}')" if end_idx < n_iterations else None
    }


# =============================================================================
# TOOL 6: List Remote Files
# =============================================================================
@mcp.tool()
def list_colab_files(path: str = "/content") -> Dict[str, Any]:
    """
    List files in Colab environment.

    Timeout: 30 seconds

    Args:
        path: Directory to list (default: /content)

    Returns:
        files: List of files with names, sizes, types
    """
    result = make_request("GET", f"/files/list?path={path}", timeout=TIMEOUTS["quick"])
    return result["data"] if result["success"] else result


# =============================================================================
# TOOL 7: Download File from Colab
# =============================================================================
@mcp.tool()
def download_from_colab(remote_path: str, local_filename: str = "") -> Dict[str, Any]:
    """
    Download a file from Colab to local machine.

    IMPORTANT: Colab files are lost when session ends!
    Download important results immediately.

    Timeout: 300 seconds (5 min for large files)

    Args:
        remote_path: Full path on Colab (e.g., '/content/model.pkl')
        local_filename: Optional custom name (default: same as remote)

    Returns:
        success: True/False
        local_path: Where file was saved
        size_mb: File size
    """
    try:
        filename = local_filename or os.path.basename(remote_path)
        local_path = os.path.join(LOCAL_SAVE_DIR, filename)

        response = requests.get(
            f"{COLAB_URL}/files/download",
            params={"path": remote_path},
            timeout=TIMEOUTS["long"],
            stream=True
        )

        if response.status_code == 404:
            return {"success": False, "error": f"File not found: {remote_path}"}

        if response.status_code != 200:
            return {"success": False, "error": f"Download failed: {response.status_code}"}

        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        size_mb = os.path.getsize(local_path) / (1024 ** 2)

        return {
            "success": True,
            "local_path": local_path,
            "size_mb": round(size_mb, 2),
            "saved_at": datetime.now().isoformat()
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# TOOL 8: Cleanup Colab Environment
# =============================================================================
@mcp.tool()
def cleanup_colab() -> Dict[str, Any]:
    """
    Free memory in Colab environment.

    Call when:
    - Memory warnings appear
    - Before loading large datasets
    - After finishing a task

    WARNING: All unsaved variables will be LOST!

    Timeout: 30 seconds

    Returns:
        memory_freed_mb: RAM freed
        variables_cleared: Count of variables removed
    """
    result = make_request("POST", "/cleanup", timeout=TIMEOUTS["quick"])
    return result["data"] if result["success"] else result


# =============================================================================
# TOOL 9: List Variables in Memory
# =============================================================================
@mcp.tool()
def list_colab_variables() -> Dict[str, Any]:
    """
    List all Python variables currently in Colab memory.

    Timeout: 15 seconds

    Returns:
        count: Number of variables
        variables: List with name, type, size/shape
    """
    result = make_request("GET", "/variables", timeout=TIMEOUTS["quick"])
    return result["data"] if result["success"] else result


# =============================================================================
# TOOL 10: Get/Resume Checkpoint
# =============================================================================
@mcp.tool()
def get_checkpoint(operation: str) -> Dict[str, Any]:
    """
    Get saved checkpoint for an operation.

    Use to resume interrupted operations or recall results.

    Args:
        operation: Name of the checkpointed operation

    Returns:
        exists: True if checkpoint found
        data: Checkpoint data if exists
    """
    checkpoint = load_checkpoint(operation)
    if checkpoint:
        return {"exists": True, **checkpoint}
    else:
        return {"exists": False, "message": f"No checkpoint found for '{operation}'"}


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    print("=" * 60, file=sys.stderr)
    print("SMART COLAB AGENT v2 - MCP Server", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Colab URL: {COLAB_URL}", file=sys.stderr)
    print(f"Local save dir: {LOCAL_SAVE_DIR}", file=sys.stderr)
    print(f"Checkpoint dir: {CHECKPOINT_DIR}", file=sys.stderr)
    print("", file=sys.stderr)
    print("Tools available:", file=sys.stderr)
    print("  - check_colab_connection()", file=sys.stderr)
    print("  - probe_colab_environment()", file=sys.stderr)
    print("  - run_code_quick(code)", file=sys.stderr)
    print("  - run_code_long(code, checkpoint_name)", file=sys.stderr)
    print("  - run_chunked_operation(...)", file=sys.stderr)
    print("  - list_colab_files(path)", file=sys.stderr)
    print("  - download_from_colab(remote_path)", file=sys.stderr)
    print("  - cleanup_colab()", file=sys.stderr)
    print("  - list_colab_variables()", file=sys.stderr)
    print("  - get_checkpoint(operation)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    mcp.run()
