from typing import Dict, Any, List, Optional
from pathlib import Path
from agora.telemetry import AuditedAsyncFlow, AuditLogger
from .workflow_nodes import MCPNode
from .parser import WorkflowParser


class MCPWorkflowFlow(AuditedAsyncFlow):
    """Orchestrate MCP entities as an Agora workflow."""
    
    def __init__(
        self,
        workflow_name: str,
        server_path: str,
        workflow_spec: List[str],
        logger: AuditLogger,
        initial_input: Optional[Dict[str, Any]] = None
    ):
        super().__init__(workflow_name, logger)
        self.server_path = server_path
        self.workflow_spec = workflow_spec
        self.initial_input = initial_input or {}
        self.nodes: Dict[str, MCPNode] = {}
        self.start_node_name = None
        
        self._build_workflow()
    
    def _build_workflow(self):
        """Parse workflow and create Agora nodes."""
        parser = WorkflowParser()
        connections = parser.parse_workflow(self.workflow_spec)
        
        if not connections:
            raise ValueError("No valid workflow connections found")
        
        ordered_nodes = parser.get_ordered_nodes(connections)
        self.start_node_name = parser.get_start_node(connections)
        
        # Create MCPNode for each unique node
        for i, node_name in enumerate(ordered_nodes):
            next_node = ordered_nodes[i + 1] if i < len(ordered_nodes) - 1 else "complete"
            
            node = MCPNode(
                name=node_name,
                audit_logger=self.audit_logger,
                entity_type="tool",
                entity_name=node_name,
                server_path=self.server_path,
                next_node=next_node
            )
            self.nodes[node_name] = node
        
        # Wire nodes using Agora's >> operator
        for source_name, action, target_name in connections:
            source_node = self.nodes[source_name]
            
            # ✅ FIX: Skip if target is "complete" (end of workflow)
            if target_name == "complete":
                continue
            
            target_node = self.nodes[target_name]
            
            if action:
                source_node - action >> target_node
            else:
                source_node - target_name >> target_node
        
        # Set start node
        self.start(self.nodes[self.start_node_name])
    
    async def run_async(self, shared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run the workflow."""
        if shared is None:
            shared = {}
        
        # ✅ FIX: Set initial input for the START NODE
        if self.initial_input and self.start_node_name:
            shared[f"{self.start_node_name}_input"] = self.initial_input
        
        await super().run_async(shared)
        
        return shared
