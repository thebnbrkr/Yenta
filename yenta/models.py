from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class TestResult(BaseModel):
    """Individual test result"""
    test_name: str
    tool: str
    arguments: Dict[str, Any]
    response: Dict[str, Any]
    status: str  # 'PASS' or 'FAIL'
    latency_ms: float
    mode: str  # 'record', 'replay', 'mock'
    failures: List[str] = []
    expected: Dict[str, Any] = {}

class TestRun(BaseModel):
    """Complete test run"""
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    spec_name: str
    server: str
    status: str  # 'completed', 'failed'
    duration_ms: float
    results: List[TestResult]
    metadata: Dict[str, Any] = {}

class Mock(BaseModel):
    """Recorded mock"""
    category: str  # 'tools', 'resources', 'prompts'
    name: str
    arguments: Dict[str, Any]
    response: Dict[str, Any]
    recorded_at: datetime = Field(default_factory=datetime.utcnow)

class Capabilities(BaseModel):
    """Server capabilities"""
    server: str
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    tools: List[Dict[str, Any]] = []
    resources: List[Dict[str, Any]] = []
    prompts: List[Dict[str, Any]] = []
