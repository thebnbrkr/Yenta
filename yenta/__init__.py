import json, yaml, time, asyncio  # ADD yaml HERE!
from pathlib import Path
from pydantic import ValidationError
from agora.telemetry import AuditedAsyncNode, AuditedAsyncBatchNode
from .schemas import SCHEMA_REGISTRY
from .mocks import MockRegistry

try:
    from fastmcp import Client
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    Client = None


class LoadSpecNode(AuditedAsyncNode):
    """Load spec YAML and place in shared dict"""

    async def prep_async(self, shared):
        return shared["spec_file"]

    async def exec_async(self, spec_file):
        spec_path = Path(spec_file)
        if not spec_path.exists():
            raise FileNotFoundError(f"Spec file not found: {spec_file}")
        
        try:
            # Validate spec file against schema
            validated_spec = validate_spec_file(spec_path)
            logger.info(f"Spec file validated successfully: {spec_file}")
            return validated_spec.model_dump()
        except ValidationError as e:
            logger.error(f"Spec validation failed for {spec_file}: {e}")
            raise ValueError(f"Invalid spec file format: {e}")

    async def post_async(self, shared, _, spec_dict):
        shared["spec"] = spec_dict
        shared["start_time"] = time.time()
        agent = spec_dict.get("agent_name", "<unnamed>")
        tools = spec_dict.get("tools", [])
        tests = spec_dict.get("custom_tests", [])
        logger.info(f"Loaded spec: {agent}")
        logger.info(f"Tools: {', '.join(tools)}")
        logger.info(f"Tests to run: {len(tests)}")
        return "run_tests"


class RunMCPTestsNode(AuditedAsyncBatchNode):
    """Run all tests against one or more MCP servers using FastMCP Client (with mocking support)"""

    def __init__(self, name, audit_logger):
        super().__init__(name, audit_logger)
        self.mock_registry = MockRegistry()

    async def prep_async(self, shared):
        spec = shared["spec"]
        tests = spec.get("custom_tests", [])

        if "mcp_servers" in spec:
            servers = spec["mcp_servers"]
        elif "mcp_server" in spec:
            servers = [spec["mcp_server"]]
        else:
            raise ValueError("spec must include mcp_server or mcp_servers")

        # Get global flags
        global_use_mocks = spec.get("use_mocks", False)
        global_record_mocks = spec.get("record_mocks", False)

        # Pass global flags WITH each test pair
        return [{
            "server_path": s, 
            "test": t,
            "global_use_mocks": global_use_mocks,
            "global_record_mocks": global_record_mocks
        } for s in servers for t in tests]

    async def exec_async(self, pair):
        """Execute a single test case using FastMCP Client (or mocks)"""
        server_path, test_case = pair["server_path"], pair["test"]
        name, tool, args = test_case["name"], test_case["tool"], test_case.get("arguments", {})
        timeout = int(test_case.get("timeout_sec", 45))

        # Determine if we should use mocks (per-test overrides global)
        use_mocks = test_case.get("use_mocks", pair.get("global_use_mocks", False))
        record_mocks = test_case.get("record_mocks", pair.get("global_record_mocks", False))
        
        mode = "real"  # Can be: mock, replay, recorded, real
        
        # --- MOCKING LOGIC ---
        start = time.time()
        
        # 1. Inline mock (highest priority)
        if use_mocks and "mock" in test_case:
            print(f"  [mocked] {name} ...")
            resp = test_case["mock"]
            latency_ms = 0.0
            mode = "mock"
        
        # 2. Replay from registry
        elif use_mocks and self.mock_registry.has_mock(tool, args):
            print(f"  [replayed] {name} ...")
            resp = self.mock_registry.get(tool, args)
            latency_ms = 0.0
            mode = "replay"
        
        # 3. Real MCP call
        else:
            if not FASTMCP_AVAILABLE:
                return {
                    "server": server_path,
                    "test_name": name,
                    "tool": tool,
                    "arguments": args,
                    "status": "FAIL",
                    "response": {"error": "FastMCP not installed"},
                    "failures": ["pip install fastmcp"],
                    "metrics": {"latency_ms": 0},
                    "mode": "error",
                    "expected": {},
                }

            mode_label = "recorded" if record_mocks else "real"
            print(f"  [{mode_label}] Running [{Path(server_path).name}] :: {name} ...")
            
            try:
                async with Client(server_path) as client:
                    result = await asyncio.wait_for(
                        client.call_tool(tool, args),
                        timeout=timeout
                    )
                    latency_ms = (time.time() - start) * 1000.0
                    
                    # Extract text from MCP response
                    if hasattr(result, 'content') and result.content:
                        content = result.content[0]
                        resp = {"result": content.text if hasattr(content, 'text') else str(content)}
                    else:
                        resp = {"result": str(result)}
                    
                    mode = "recorded" if record_mocks else "real"
                    
                    # Record if requested
                    if record_mocks:
                        self.mock_registry.record(tool, args, resp)
                        
            except asyncio.TimeoutError:
                latency_ms = (time.time() - start) * 1000.0
                resp = {"error": f"Timeout after {timeout}s"}
                mode = "error"
            except Exception as e:
                latency_ms = (time.time() - start) * 1000.0
                resp = {"error": f"{type(e).__name__}: {str(e)}"}
                mode = "error"

        # --- VALIDATION LOGIC (same for mocks and real calls) ---
        status = "PASS" if "error" not in resp else "FAIL"
        failures = []
        details = {"latency_ms": round(latency_ms, 2)}

        schema_name = test_case.get("expected_schema")
        if status == "PASS" and schema_name:
            model = SCHEMA_REGISTRY.get(schema_name)
            if not model:
                status, failures = "FAIL", [f"Unknown schema '{schema_name}'"]
            else:
                try:
                    model(**resp)
                except ValidationError as e:
                    status, failures = "FAIL", [f"Schema validation failed: {e}"]

        # Keyword checks (CASE-INSENSITIVE)
        keywords = test_case.get("expected_keywords", [])
        if status == "PASS" and keywords:
            jam = json.dumps(resp, ensure_ascii=False).lower()  # Convert to lowercase
            missing = [k for k in keywords if k.lower() not in jam]  # Compare lowercase
            if missing:
                status, failures = "FAIL", [f"Missing keywords: {missing}"]

        metrics = test_case.get("expected_metrics", {})
        max_latency = metrics.get("max_latency_ms")
        if status == "PASS" and isinstance(max_latency, (int, float)):
            if latency_ms > float(max_latency):
                status, failures = "FAIL", [f"Latency {latency_ms:.1f} > {max_latency}"]

        return {
            "server": "mock" if mode in ["mock", "replay"] else server_path,
            "test_name": name,
            "tool": tool,
            "arguments": args,
            "status": status,
            "response": resp,
            "failures": failures,
            "metrics": details,
            "mode": mode,  # NEW: Track whether this was mocked/replayed/recorded/real
            "expected": {"schema": schema_name, "keywords": keywords, "metrics": metrics},
        }

    async def post_async(self, shared, _, results):
        shared["results"] = results
        total, passed = len(results), sum(1 for r in results if r["status"] == "PASS")
        logger.info(f"Completed: {passed}/{total} tests passed")
        
        # FIXED: Save run history with proper TestResult construction
        try:
            duration_ms = (time.time() - shared.get("start_time", time.time())) * 1000
            run = TestRun(
                session_id=self.audit_logger.session_id,
                spec_name=Path(shared["spec_file"]).name,
                server=shared["spec"].get("mcp_server", shared["spec"].get("mcp_servers", ["unknown"])[0]),
                status="completed",
                duration_ms=duration_ms,
                results=[TestResult(
                    test_name=r["test_name"],
                    tool=r["tool"],
                    arguments=r["arguments"],
                    response=r["response"],
                    status=r["status"],
                    latency_ms=r["metrics"].get("latency_ms", 0.0),  # ✅ FIXED: Extract from metrics
                    mode=r["mode"],
                    failures=r.get("failures", []),
                    expected=r.get("expected", {})
                ) for r in results]
            )
            self.mock_registry.save_run(run)
        except Exception as e:
            logger.warning(f"Could not save run history: {e}")
        
        return "report"


class GenerateReportNode(AuditedAsyncNode):
    """Pretty + JSON reports (with mock/replay indicators)"""

    async def prep_async(self, shared): 
        return shared["results"]

    async def exec_async(self, results):
        servers = sorted(set(r["server"] for r in results))
        by_server = {s: [r for r in results if r["server"] == s] for s in servers}

        lines = ["="*70, "MCP TEST REPORT", "="*70]
        for s in servers:
            block = by_server[s]
            total, passed = len(block), sum(1 for r in block if r["status"] == "PASS")
            lines += [f"\nServer: {s}", f"Summary: {passed}/{total} passed"]
            for r in block:
                icon = "✅" if r["status"] == "PASS" else "❌"
                mode_badge = f"[{r.get('mode', 'real')}]"  # NEW: Show mode
                lines.append(f"\n{icon} {r['test_name']} {mode_badge}  [{r['metrics'].get('latency_ms','?')} ms]")
                if r["failures"]:
                    for f in r["failures"]:
                        lines.append(f"   - {f}")
                lines.append(f"   Tool: {r['tool']}")
                lines.append(f"   Args: {r['arguments']}")
                lines.append(f"   Resp: {json.dumps(r['response'], indent=2, ensure_ascii=False)[:800]}")

        with open("results.json", "w") as f:
            json.dump({"results": results}, f, indent=2, ensure_ascii=False)

        return "\n".join(lines)

    async def post_async(self, shared, _, report):
        logger.info("Test report generated")
        shared["report"] = report
        return "complete"