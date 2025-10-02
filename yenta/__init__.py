import json, yaml, subprocess, time
from pathlib import Path
from typing import Any, Dict, List
from pydantic import ValidationError

# Import telemetry base classes from Agora
from agora.telemetry import AuditedNode, AuditedBatchNode
from .schemas import SCHEMA_REGISTRY


class LoadSpecNode(AuditedNode):
    """Load spec YAML and place in shared dict"""

    def prep(self, shared):
        return shared["spec_file"]

    def exec(self, spec_file):
        with open(spec_file) as f:
            return yaml.safe_load(f)

    def post(self, shared, _, spec_dict):
        shared["spec"] = spec_dict
        agent = spec_dict.get("agent_name", "<unnamed>")
        tools = spec_dict.get("tools", [])
        tests = spec_dict.get("custom_tests", [])
        print(f"\n✓ Loaded spec: {agent}")
        print(f"  Tools: {', '.join(tools)}")
        print(f"  Tests to run: {len(tests)}\n")
        return "run_tests"


class RunMCPTestsNode(AuditedBatchNode):
    """Run all tests against one or more MCP servers"""

    def prep(self, shared):
        spec = shared["spec"]
        tests: List[Dict[str, Any]] = spec.get("custom_tests", [])

        if "mcp_servers" in spec:
            servers = spec["mcp_servers"]
        elif "mcp_server" in spec:
            servers = [spec["mcp_server"]]
        else:
            raise ValueError("spec must include mcp_server or mcp_servers")

        # Cartesian product [(server, test)]
        return [{"server_path": s, "test": t} for s in servers for t in tests]

    def _call_mcp(self, server_path: str, tool_name: str, arguments: Dict[str, Any], timeout_sec: int = 45):
        req = json.dumps({"tool": tool_name, "arguments": arguments})
        start = time.time()
        try:
            proc = subprocess.Popen(
                ["python", server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = proc.communicate(input=req + "\n", timeout=timeout_sec)
            latency_ms = (time.time() - start) * 1000.0

            if stderr:
                return {"error": stderr.strip()}, latency_ms

            try:
                data = json.loads(stdout.strip())
            except Exception as e:
                return {"error": f"Malformed JSON: {e}\nRAW: {stdout[:200]}..."}, latency_ms

            return data, latency_ms
        except subprocess.TimeoutExpired:
            return {"error": f"Timeout after {timeout_sec}s"}, (time.time() - start) * 1000.0
        except Exception as e:
            return {"error": str(e)}, (time.time() - start) * 1000.0

    def exec(self, pair):
        server_path, test_case = pair["server_path"], pair["test"]
        name, tool, args = test_case["name"], test_case["tool"], test_case.get("arguments", {})
        timeout = int(test_case.get("timeout_sec", 45))

        print(f"  Running [{Path(server_path).name}] :: {name} ...")
        resp, latency_ms = self._call_mcp(server_path, tool, args, timeout)

        status = "PASS" if "error" not in resp else "FAIL"
        failures, details = [], {"latency_ms": round(latency_ms, 2)}

        # schema validation
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

        # keyword checks
        keywords = test_case.get("expected_keywords", [])
        if status == "PASS" and keywords:
            jam = json.dumps(resp, ensure_ascii=False)
            missing = [k for k in keywords if k not in jam]
            if missing:
                status, failures = "FAIL", [f"Missing keywords: {missing}"]

        # metric assertions
        metrics = test_case.get("expected_metrics", {})
        max_latency = metrics.get("max_latency_ms")
        if status == "PASS" and isinstance(max_latency, (int, float)):
            if latency_ms > float(max_latency):
                status, failures = "FAIL", [f"Latency {latency_ms:.1f} > {max_latency}"]

        return {
            "server": server_path,
            "test_name": name,
            "tool": tool,
            "arguments": args,
            "status": status,
            "response": resp,
            "failures": failures,
            "metrics": details,
            "expected": {"schema": schema_name, "keywords": keywords, "metrics": metrics},
        }

    def post(self, shared, _, results):
        shared["results"] = results
        total, passed = len(results), sum(1 for r in results if r["status"] == "PASS")
        print(f"\n  Completed: {passed}/{total} tests passed\n")
        return "report"


class GenerateReportNode(AuditedNode):
    """Pretty + JSON reports"""

    def prep(self, shared): return shared["results"]

    def exec(self, results):
        servers = sorted(set(r["server"] for r in results))
        by_server = {s: [r for r in results if r["server"] == s] for s in servers}

        lines = ["="*70, "MCP TEST REPORT", "="*70]
        for s in servers:
            block = by_server[s]
            total, passed = len(block), sum(1 for r in block if r["status"] == "PASS")
            lines += [f"\nServer: {s}", f"Summary: {passed}/{total} passed"]
            for r in block:
                icon = "✅" if r["status"] == "PASS" else "❌"
                lines.append(f"\n{icon} {r['test_name']}  [{r['metrics'].get('latency_ms','?')} ms]")
                if r["failures"]:
                    for f in r["failures"]:
                        lines.append(f"   - {f}")
                lines.append(f"   Tool: {r['tool']}")
                lines.append(f"   Args: {r['arguments']}")
                lines.append(f"   Resp: {json.dumps(r['response'], indent=2, ensure_ascii=False)[:800]}")

        with open("results.json", "w") as f:
            json.dump({"results": results}, f, indent=2, ensure_ascii=False)

        return "\n".join(lines)

    def post(self, shared, _, report):
        print(report)
        shared["report"] = report
        return "complete"
