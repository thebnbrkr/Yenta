"""Agora flow for MCP workflow orchestration."""

from typing import Dict, Any, List, Optional
from pathlib import Path
from agora.telemetry import AuditedAsyncFlow, AuditLogger
from .workflow_nodes import MCPNode
from .parser import WorkflowParser
from .discovery import MCPDiscovery


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
        """
        Initialize workflow flow.
        
        Args:
            workflow_name: Custom name for this workflow
            server_path: Path to FastMCP server
            workflow_spec: List of workflow lines (e.g., ["tool_a >> tool_b"])
            logger: Agora audit logger
            initial_input: Optional initial input for first node
        """
        super().__init__(workflow_name, logger)
        self.server_path = server_path
        self.workflow_spec = workflow_spec
        self.initial_input = initial_input or {}
        self.nodes: Dict[str, MCPNode] = {}
        
        # Build the workflow
        self._build_workflow()
    
    def _build_workflow(self):
        """Parse workflow and create Agora nodes."""
        # Parse workflow syntax
        parser = WorkflowParser()
        connections = parser.parse_workflow(self.workflow_spec)
        
        if not connections:
            raise ValueError("No valid workflow connections found")
        
        # Get ordered nodes and start node
        ordered_nodes = parser.get_ordered_nodes(connections)
        start_node_name = parser.get_start_node(connections)
        
        # Create MCPNode for each unique node
        # Assume all are tools for now (discovery happens at runtime)
        for i, node_name in enumerate(ordered_nodes):
            # Determine next node
            next_node = ordered_nodes[i + 1] if i < len(ordered_nodes) - 1 else None
            
            # Create node
            node = MCPNode(
                name=node_name,
                audit_logger=self.audit_logger,
                entity_type="tool",  # Default to tool
                entity_name=node_name,
                server_path=self.server_path,
                next_node=next_node
            )
            self.nodes[node_name] = node
        
        # Wire nodes using Agora's >> operator
        for source_name, action, target_name in connections:
            source_node = self.nodes[source_name]
            target_node = self.nodes[target_name]
            
            if action:
                # Conditional routing: source - "action" >> target
                source_node - action >> target_node
            else:
                # Direct routing: source >> target
                source_node - target_name >> target_node
        
        # Set start node
        self.start(self.nodes[start_node_name])
    
    async def run_async(self, shared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Run the workflow.
        
        Args:
            shared: Optional shared state dict (will be created if not provided)
        
        Returns:
            The shared dict with all node outputs
        """
        if shared is None:
            shared = {}
        
        # Set initial input for first node if provided
        if self.initial_input:
            start_node_name = list(self.nodes.keys())[0]
            shared[f"{start_node_name}_input"] = self.initial_input
        
        # Run the flow
        await super().run_async(shared)
        
        return shared


async def build_and_run_workflow(
    workflow_name: str,
    server_path: str,
    workflow_lines: List[str],
    initial_input: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Helper function to build and run a workflow.
    
    Args:
        workflow_name: Custom name for the workflow
        server_path: Path to FastMCP server
        workflow_lines: Workflow specification lines
        initial_input: Initial input for first node
        session_id: Optional session ID for audit logging
    
    Returns:
        Shared dict with all outputs
    """
    logger = AuditLogger(session_id=session_id or f"workflow-{workflow_name}")
    
    flow = MCPWorkflowFlow(
        workflow_name=workflow_name,
        server_path=server_path,
        workflow_spec=workflow_lines,
        logger=logger,
        initial_input=initial_input
    )
    
    result = await flow.run_async()
    
    return result
