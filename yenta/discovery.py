# yenta/discovery.py
"""Discover MCP entities (tools/prompts/resources) from FastMCP servers."""

import asyncio
from typing import Dict, List, Any
from pathlib import Path

try:
    from fastmcp import Client
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    Client = None


class MCPDiscovery:
    """Discover MCP entities from a server."""
    
    def __init__(self, server_path: str):
        self.server_path = server_path
    
    async def discover_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """Discover all tools, prompts, and resources from the MCP server."""
        if not FASTMCP_AVAILABLE:
            raise RuntimeError("FastMCP not installed. Run: pip install fastmcp")
        
        entities = {
            "tools": [],
            "prompts": [],
            "resources": []
        }
        
        async with Client(self.server_path) as client:
            # Discover tools
            tools_result = await client.list_tools()
            entities["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                }
                for tool in tools_result.tools
            ]
            
            # Discover prompts
            prompts_result = await client.list_prompts()
            entities["prompts"] = [
                {
                    "name": prompt.name,
                    "description": prompt.description,
                    "arguments": prompt.arguments
                }
                for prompt in prompts_result.prompts
            ]
            
            # Discover resources
            resources_result = await client.list_resources()
            entities["resources"] = [
                {
                    "uri": str(resource.uri),
                    "name": resource.name,
                    "description": resource.description
                }
                for resource in resources_result.resources
            ]
        
        return entities
