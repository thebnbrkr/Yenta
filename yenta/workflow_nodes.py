# yenta/workflow_nodes.py
"""Agora nodes for MCP workflow orchestration."""

import asyncio
from typing import Any, Dict, Optional
from agora.telemetry import AuditedAsyncNode

try:
    from fastmcp import Client
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    Client = None


class MCPNode(AuditedAsyncNode):
    """Agora node that calls an MCP entity (tool/prompt/resource)."""
    
    def __init__(
        self, 
        name: str, 
        audit_logger, 
        entity_type: str,
        entity_name: str, 
        server_path: str,
        next_node: Optional[str] = None
    ):
        """
        Initialize MCP node.
        
        Args:
            name: Node name for Agora workflow
            audit_logger: Agora audit logger
            entity_type: 'tool', 'prompt', or 'resource'
            entity_name: Name of the MCP entity to call
            server_path: Path to FastMCP server
            next_node: Name of next node in linear workflow
        """
        super().__init__(name, audit_logger)
        self.entity_type = entity_type
        self.entity_name = entity_name
        self.server_path = server_path
        self.next_node = next_node
    
    async def prep_async(self, shared: Dict[str, Any]) -> Any:
        """Get input from previous node's output."""
        # Check if this is the first node with initial input
        if f"{self.name}_input" in shared:
            return shared[f"{self.name}_input"]
        
        # Get output from previous node
        prev_output_key = shared.get("_prev_output_key")
        if prev_output_key:
            return shared.get(prev_output_key, {})
        
        # No input available
        return {}
    
    async def exec_async(self, input_data: Any) -> Any:
        """Execute MCP entity call."""
        if not FASTMCP_AVAILABLE:
            raise RuntimeError("FastMCP not installed")
        
        async with Client(self.server_path) as client:
            if self.entity_type == "tool":
                result = await client.call_tool(self.entity_name, input_data)
                
                # Extract content from MCP response
                if hasattr(result, 'content') and result.content:
                    content = result.content[0]
                    if hasattr(content, 'text'):
                        return {"result": content.text}
                    return {"result": str(content)}
                
                return {"result": str(result)}
            
            elif self.entity_type == "prompt":
                result = await client.get_prompt(self.entity_name, input_data)
                return {"messages": result.messages}
            
            elif self.entity_type == "resource":
                result = await client.read_resource(input_data.get("uri"))
                return {"contents": result.contents}
            
            else:
                raise ValueError(f"Unknown entity type: {self.entity_type}")
    
    async def post_async(self, shared: Dict[str, Any], _, result: Any) -> str:
        """Store output and return routing key."""
        # Store result for next node
        output_key = f"{self.name}_output"
        shared[output_key] = result
        shared["_prev_output_key"] = output_key
        
        # Return routing key for Agora
        return self.next_node if self.next_node else "complete"
