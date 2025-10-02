from agora.telemetry import AuditedFlow, AuditLogger
from yenta import LoadSpecNode, RunMCPTestsNode, GenerateReportNode


class MCPTestFlow(AuditedFlow):
    """Tie nodes together into a full MCP test run"""

    def __init__(self, logger: AuditLogger):
        super().__init__("MCPTestFlow", logger)
        load = LoadSpecNode("load_spec", logger)
        run  = RunMCPTestsNode("run_tests", logger)
        rep  = GenerateReportNode("generate_report", logger)

        self.start(load)
        load - "run_tests" >> run
        run  - "report"    >> rep
