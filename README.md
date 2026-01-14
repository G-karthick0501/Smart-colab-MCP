# Smart Colab MCP Bridge (Experimental)

This repository contains an experimental setup that connects Claude Desktop to a Google Colab runtime using a lightweight Flask server exposed via ngrok. The goal is to enable controlled, resource-aware remote execution of Python code on Colab (CPU/GPU) while orchestrating tasks locally via Claude Desktop.

**This repository reflects the system as originally built, without later hardening or refactoring.**

---

## 📊 System Architecture

```
      ┌────────────────┐          ┌───────────────────┐
      │ Claude Desktop │          │   Google Colab    │
      │   (Reasoning)  │          │    (Compute)      │
      └───────┬────────┘          └─────────┬─────────┘
              │                             │
       JSON-RPC (Stdio)                Flask Server
              │                             │
      ┌───────▼────────┐          ┌─────────▼─────────┐
      │ Local MCP Agent│◄────────►│    ngrok Tunnel   │
      │ (State/Config) │   HTTP   │  (Public URL)     │
      └────────────────┘          └───────────────────┘
```

**How it works:**
1. **Local MCP Agent:** Lightweight Python script runs on your PC via Claude Desktop. Handles timeouts, checkpointing, and file management.
2. **Remote Executor:** Colab notebook exposes a Flask API via ngrok tunnel.
3. **The Bridge:** Claude sends code → Local Agent → Colab executes → Results return to Claude.

**Important:** Claude Desktop automatically launches MCP servers. The Colab notebook must be started manually to provide the ngrok endpoint.

---

## ✨ Features

- **Remote Execution:** Run Pandas, PyTorch, Scikit-Learn on Colab GPU/CPU
- **Smart Timeouts:**
  - Quick Mode (2 min): Variable checks, light computation
  - Long Mode (10 min): Model training, dataset downloads
- **Chunked Operations:** Break massive loops into safe batches to avoid timeouts
- **Local Persistence:**
  - Checkpoint resumability for long-running tasks
  - Automatic file downloads from Colab `/content` to local machine
- **Environment Probing:** Query RAM, GPU, and installed packages before execution
- **Memory Management:** Cleanup endpoint to free RAM without restarting runtime

---

## 📂 Repository Structure

```
smart-colab-mcp/
├── agent/
│   └── mcp_smart_colab_v2.py       # Local MCP bridge (reads from env vars)
├── colab/
│   └── smart_colab_executor.ipynb  # Colab backend (Flask + ngrok)
├── config/
│   └── claude_desktop_config.example.json
├── requirements.txt
└── README.md
```

---

## 🚀 Setup Instructions

### Phase 1: Colab Setup

1. Open `colab/smart_colab_executor.ipynb` in Google Colab
2. **Set your ngrok auth token:**
   ```python
   !ngrok authtoken YOUR_TOKEN_HERE
   ```
   Get a free token at [ngrok.com/dashboard](https://dashboard.ngrok.com)
3. Run all cells in the notebook
4. **Copy the public HTTPS URL** printed (e.g., `https://xxxx-xx-xx.ngrok-free.app`)
5. **Keep the notebook running** - closing it kills the server

### Phase 2: Local Setup

```bash
git clone https://github.com/G-karthick0501/Smart-colab-MCP.git
cd Smart-colab-MCP
pip install -r requirements.txt
```

**Required packages:**
- `mcp` - Model Context Protocol
- `requests` - HTTP client
- `flask` - Web framework (Colab-side)
- `pyngrok` - ngrok Python wrapper (Colab-side)

### Phase 3: Configure Claude Desktop

**Location:** `%APPDATA%\Claude\claude_desktop_config.json` (Windows)

**Example configuration:**
```json
{
  "mcpServers": {
    "smart-colab": {
      "command": "C:\\Path\\To\\Python.exe",
      "args": ["C:\\Path\\To\\agent\\mcp_smart_colab_v2.py"],
      "env": {
        "COLAB_URL": "https://your-ngrok-url.ngrok-free.app",
        "LOCAL_SAVE_DIR": "C:\\Path\\To\\results",
        "CHECKPOINT_DIR": "C:\\Path\\To\\checkpoints"
      }
    }
  }
}
```

**Important:**
- Use **double backslashes** (`\\`) in Windows paths
- Replace `COLAB_URL` with your actual ngrok URL from Phase 1
- Create `LOCAL_SAVE_DIR` and `CHECKPOINT_DIR` folders beforehand
- Restart Claude Desktop after editing config

---

## 🛠️ Available Tools

| Tool | Description | Timeout |
|------|-------------|---------|
| `check_colab_connection` | Verify ngrok tunnel is active | 10s |
| `probe_colab_environment` | Get GPU/RAM/packages info | 30s |
| `run_code_quick` | Execute short Python snippets | 2 min |
| `run_code_long` | Execute heavy tasks (training/downloads) | 10 min |
| `run_chunked_operation` | Process loops in batches with resume support | 5 min/batch |
| `list_colab_files` | List files in Colab `/content` directory | 30s |
| `download_from_colab` | Download file to `LOCAL_SAVE_DIR` | 5 min |
| `cleanup_colab` | Free RAM/GPU memory | 30s |
| `list_colab_variables` | Show runtime variables and shapes | 15s |
| `get_checkpoint` | Retrieve saved checkpoint data | Instant |

---

## 🔍 Verification & Troubleshooting

### Check Running Processes

**Windows:**
```cmd
tasklist /fi "imagename eq python.exe"
```

**Expected output:**
```
Image Name           PID   Session    Mem Usage
Claude.exe          1234   Console    450,000 K
python.exe          5678   Console     80,000 K  ← Memory MCP (if configured)
python.exe          9012   Console     60,000 K  ← Colab MCP
```

### Test Colab Health Endpoint

```bash
curl https://your-ngrok-url/health
```

**Expected response:**
```json
{
  "status": "ok",
  "uptime_minutes": 15,
  "memory_available_gb": 10.5,
  "memory_used_pct": 15.2
}
```

### Common Issues

| Problem | Cause | Solution |
|---------|-------|----------|
| `Connection refused` | Colab notebook not running | Re-run notebook cells |
| `COLAB_URL not set` | Missing env variable | Check Claude Desktop config |
| ngrok URL changed | Notebook restarted | Update config with new URL |
| `404 Not Found` | Wrong endpoint path | Verify URL includes `/health` |
| Timeout on execution | Code takes >10 min | Use `run_chunked_operation` |
| Memory errors | Colab RAM full | Call `cleanup_colab()` |
| Files not found | Wrong Colab path | Check `/content/` directory |

---

## 🔒 Security Considerations

### Known Risks (Not Hardened)

- **Arbitrary Code Execution:** The `/execute` endpoint runs any Python code without validation
- **No Authentication:** ngrok URL is publicly accessible while notebook runs
- **No Sandboxing:** Code executes with full Colab runtime permissions
- **Single-Threaded:** No execution locking; concurrent requests may conflict
- **Public Exposure:** ngrok tunnel can be discovered if URL leaks

### Recommended Practices

**For Users:**
1. Never share ngrok URLs publicly
2. Review all code before execution
3. Use dedicated Google account for Colab experiments
4. Terminate sessions immediately after use
5. Monitor Colab activity dashboard

**Not Implemented (Future Work):**
- Request signing / HMAC authentication
- IP whitelisting
- Execution locks (`threading.Lock`)
- Dangerous operation restrictions
- Rate limiting

---

## 📋 Known Limitations

These are **intentionally documented** and tracked for future work:

- **Execution Model:** Synchronous, blocks Flask worker thread
- **No Concurrency Control:** Parallel requests may cause race conditions
- **Output Size Limits:** Very large outputs may exceed transport limits
- **Chunked Execution:** Assumes simple loop bodies; complex indentation may break
- **No Persistence:** Session state lost when Colab runtime disconnects
- **Session Lifetime:** Depends on Colab's idle timeout (~90 minutes)
- **ngrok Rotation:** URL changes every session (unless paid plan)
- **Flask Host Binding:** Should use `host="0.0.0.0"` for reliability

---

## 🔮 Future Work

Planned improvements (tracked as GitHub Issues):

**Security & Auth:**
- [ ] Add request signing / API key authentication
- [ ] Implement IP whitelisting
- [ ] Restrict dangerous Python operations (`os.system`, `subprocess`, etc.)
- [ ] Add structured logging with execution IDs

**Reliability:**
- [ ] Add execution locking mechanism (`threading.Lock`)
- [ ] Implement job queueing for concurrent requests
- [ ] Improve chunked execution robustness (handle complex indentation)
- [ ] Add `/shutdown` endpoint for clean server termination

**Features:**
- [ ] Persist remote state externally (Google Drive sync)
- [ ] Replace ngrok with self-hosted tunnel (Tailscale, Cloudflare)
- [ ] Support multiple runtimes (Kaggle, VM, local Docker)
- [ ] Add streaming stdout for long operations
- [ ] Implement auto-reconnect on Colab disconnect

---

## 🔄 How MCP Communication Works

```
┌─────────────────┐
│ Claude Desktop  │  Reads config.json
│                 │  Spawns MCP servers as subprocesses
└────────┬────────┘
         │
         │ JSON-RPC via stdin/stdout
         │
┌────────▼────────┐
│ MCP Server      │  Python process on your PC
│ (mcp_smart_     │  Reads COLAB_URL from environment
│  colab_v2.py)   │
└────────┬────────┘
         │
         │ HTTP POST/GET
         │
┌────────▼────────┐
│ ngrok Tunnel    │  Public HTTPS → Colab VM
└────────┬────────┘
         │
┌────────▼────────┐
│ Flask Server    │  Running in Colab notebook
│ (Colab Runtime) │  Executes Python via exec()
└─────────────────┘
```

**Example JSON-RPC message:**
```json
// Request from Claude
{
  "jsonrpc": "2.0",
  "method": "run_code_quick",
  "params": {"code": "print(2 + 2)"},
  "id": 1
}

// Response from MCP
{
  "jsonrpc": "2.0",
  "result": {
    "success": true,
    "stdout": "4\n",
    "execution_time_sec": 0.12
  },
  "id": 1
}
```

**Key Points:**
- MCP servers start **automatically** when Claude Desktop launches
- Communication between Claude and MCP is **local** (stdin/stdout)
- Communication between MCP and Colab is **HTTP** (via ngrok)
- Colab notebook must be **manually started** and kept running

---

## 📋 Recommended .gitignore

```
# Python
venv/
__pycache__/
*.pyc
*.pyo

# Local storage
results/
checkpoints/
memory_db/
memory_backups/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Secrets
*.token
.env
```

---

## 🎯 Status & Motivation

**Current Status:**
- ✅ Experimental proof-of-concept
- ✅ Single-user, local use only
- ❌ Not hardened for security
- ❌ Not production-ready

**Why This Exists:**
This project was built to explore:
- Practical MCP orchestration patterns
- Remote execution without SSH complexity
- Managing Colab's transient runtime constraints
- Long-running ML workflows with checkpointing
- Separation of concerns: reasoning (Claude) vs compute (Colab)

**What Makes This Different:**
- **Execution Taxonomy:** Explicit quick/long/chunked modes
- **Local Checkpointing:** Resume after crashes or disconnects
- **Probe-First Discipline:** Check resources before execution
- **Failure Containment:** Proper timeout handling and error surfaces

---

## 📚 Additional Resources

- [MCP Protocol Specification](https://spec.modelcontextprotocol.io/)
- [Claude Desktop MCP Guide](https://docs.anthropic.com/claude/docs/model-context-protocol)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [ngrok Documentation](https://ngrok.com/docs)
- [Google Colab FAQ](https://research.google.com/colaboratory/faq.html)

---

## 🤝 Contributing

Contributions welcome via Issues and Pull Requests!

**Before submitting:**
- Remove personal paths and tokens
- Test with fresh Colab session
- Document any new endpoints or tools
- Update this README if architecture changes

**Good First Issues:**
- Add execution locks to prevent concurrent runs
- Implement basic request authentication
- Improve error messages and logging
- Add unit tests for MCP tools

---

## ⚠️ Disclaimer

This code executes arbitrary Python remotely. It is **not safe** for multi-user or public deployment. Use only in trusted environments with trusted code.

**The user is responsible for:**
- Reviewing all code before execution
- Managing ngrok URL privacy
- Understanding execution permissions
- Monitoring Colab usage and costs

**The authors provide:**
- Educational example code
- Documentation of known risks
- No warranties or guarantees

**Use at your own risk.** Not recommended for production use.

---

## 🙏 Acknowledgments

- Inspired by [doobidoo/mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) patterns
- Built with [FastMCP](https://github.com/jlowin/fastmcp), [Flask](https://flask.palletsprojects.com/), and [ngrok](https://ngrok.com)
- Thanks to the Anthropic team for the MCP protocol

---

## 📝 License

MIT License - free to use with attribution

---

**Maintained by:** [G-karthick0501](https://github.com/G-karthick0501)  
**Repository:** [github.com/G-karthick0501/Smart-colab-MCP](https://github.com/G-karthick0501/Smart-colab-MCP)  
**Last Updated:** January 2026
