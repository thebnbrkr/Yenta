# Yenta 🎭

**Spec-driven MCP Testing & Workflow Orchestration Framework**

Yenta is a powerful framework for testing Model Context Protocol (MCP) servers and orchestrating complex workflows. It provides intelligent parameter mapping, mock recording/replay, auto-discovery, and custom node support.

## ✨ Features

### 🧪 **MCP Testing**
- **Spec-driven testing** with YAML configuration files
- **Mock recording & replay** for offline testing
- **Schema validation** and keyword checking
- **Performance metrics** and latency tracking
- **Multiple server support** with parallel execution

### 🔗 **Workflow Orchestration**
- **Intelligent parameter mapping** - automatically matches output keys to input parameters
- **Explicit parameter control** - specify exactly which parameters to pass
- **Custom nodes** - mix MCP tools with Python logic (ValidationNode, RoutingNode, TransformNode)
- **YAML workflow definitions** - declarative workflow configuration
- **Conditional routing** - route based on validation results

### 🔍 **Auto-Discovery**
- **AST-based discovery** - scan FastMCP servers without importing
- **Runtime discovery** - inspect running MCP servers
- **Schema extraction** - automatically extract input/output schemas
- **Entity cataloging** - tools, prompts, and resources

### 📊 **Registry & Management**
- **Organized mock storage** - separate tools, resources, prompts
- **Test run history** - track all test executions
- **Workflow registry** - manage reusable workflows
- **Rich CLI** - comprehensive command-line interface

## 🚀 Quick Start

### Installation

```bash
pip install -e .
```

### Basic MCP Testing

1. **Create a test spec** (`test_spec.yaml`):
```yaml
agent_name: "My MCP Agent"
mcp_server: "my_server.py"
tools: ["search_docs", "extract_text"]

custom_tests:
  - name: "Search Test"
    tool: "search_docs"
    arguments:
      query: "python tutorial"
      limit: 5
    expected_keywords: ["python", "tutorial"]
    expected_metrics:
      max_latency_ms: 2000

  - name: "Extract Test"
    tool: "extract_text"
    arguments:
      url: "https://example.com"
    expected_schema: "ExpectedTask"
```

2. **Run tests**:
```bash
# Run tests normally
yenta run test_spec.yaml

# Record responses for replay
yenta record test_spec.yaml

# Replay using recorded mocks
yenta replay test_spec.yaml
```

### Workflow Orchestration

1. **Create a workflow** (`workflow.yaml`):
```yaml
workflow_name: "smart_search"
mcp_server: "my_server.py"

workflow:
  - scrape_url >> extract_links          # Auto-mapped parameters
  - extract_links >> filter_links[urls]   # Explicit parameters
  - filter_links >> save_results         # Auto-mapped parameters

initial_input:
  url: "https://example.com"
```

2. **Run workflow**:
```bash
yenta workflow workflow.yaml
```

### Custom Nodes

1. **Create custom logic** (`my_nodes.py`):
```python
from yenta.custom_nodes import ValidationNode

class CheckCacheNode(ValidationNode):
    def validate(self, input_data):
        if input_data.get("cache_hit"):
            return "hit"  # Route to cached result handler
        return "miss"    # Route to fetch data
```

2. **Use in workflow**:
```yaml
workflow_name: "cached_search"
mcp_server: "my_server.py"
custom_nodes: "my_nodes.py"

workflow:
  - check_cache >> search_docs[query]
  - check_cache - 'hit' >> return_cached
  - check_cache - 'miss' >> search_docs[query]
```

## 📋 CLI Commands

### Testing Commands
```bash
# Run tests from spec
yenta run spec.yaml [--record] [--replay]

# Record responses for replay
yenta record spec.yaml

# Replay using mocks
yenta replay spec.yaml

# Show test history
yenta history [--limit 10]
```

### Workflow Commands
```bash
# Run workflow
yenta workflow workflow.yaml [--input '{"key": "value"}']

# List registered workflows
yenta workflows list [--tag search]

# Register workflows
yenta workflows register --python my_workflows.py
yenta workflows register --yaml workflows/

# Run registered workflow
yenta workflows run search_workflow
```

### Discovery Commands
```bash
# Discover MCP entities
yenta discover my_server.py [--method ast|runtime] [--save]

# Show registry status
yenta status

# Inspect recorded mocks
yenta inspect [--tool search_docs] [--category tools]

# Clear mocks
yenta clear [--category tools] [--yes]
```

### Utility Commands
```bash
# Show detailed metrics
yenta metrics --latest
yenta metrics --session my-session-123

# Generate workflow diagram
yenta visualize --workflow search_flow --output diagram.mmd
```

## 🏗️ Architecture

### Core Components

1. **Test Flow** (`flow.py`) - Orchestrates test execution pipeline
2. **Workflow Flow** (`workflow_flow.py`) - Handles complex workflow orchestration
3. **Registry** (`registry.py`) - Manages mocks, runs, and capabilities
4. **Auto-Discovery** (`autodiscovery.py`) - Scans MCP servers for entities
5. **Custom Nodes** (`custom_nodes.py`) - Framework for user-defined logic
6. **CLI** (`cli_enhanced.py`) - Rich command-line interface

### Data Flow

```
YAML Spec → LoadSpecNode → RunMCPTestsNode → GenerateReportNode
     ↓              ↓              ↓              ↓
  Parse Spec    Execute Tests   Store Results   Generate Report
```

### Workflow Flow

```
Initial Input → Node1 → Node2 → Node3 → Final Output
     ↓           ↓       ↓       ↓         ↓
  Auto-map   Execute  Execute  Execute   Results
  Params     Tool     Tool     Tool
```

## 🔧 Advanced Usage

### Parameter Mapping Strategies

1. **Auto-mapping** (default):
```yaml
workflow:
  - scrape_url >> extract_links  # Automatically matches parameter names
```

2. **Explicit mapping**:
```yaml
workflow:
  - scrape_url >> extract_links[content]  # Only pass 'content' parameter
```

3. **Multiple parameters**:
```yaml
workflow:
  - scrape_url >> process_page[url, title, content]  # Pass multiple params
```

### Custom Node Types

- **ValidationNode** - Route based on data validation
- **RoutingNode** - Complex routing decisions
- **TransformNode** - Data transformation between nodes

### Mock Management

```bash
# View mock statistics
yenta status

# Inspect specific mocks
yenta inspect --tool search_docs

# Clear old mocks
yenta clear --category tools --yes
```

## 📁 Project Structure

```
yenta/
├── __init__.py          # Core test execution nodes
├── flow.py              # Basic test flow orchestration
├── workflow_flow.py     # Advanced workflow orchestration
├── workflow_nodes.py    # MCP node implementations
├── workflow_registry.py # Workflow management
├── custom_nodes.py      # Custom node framework
├── registry.py          # Mock and run storage
├── autodiscovery.py     # MCP entity discovery
├── discovery.py         # Runtime discovery
├── parser.py            # Workflow parsing
├── models.py            # Data models
├── schemas.py           # Validation schemas
├── mocks.py             # Legacy mock support
├── cli.py               # Basic CLI
└── cli_enhanced.py      # Enhanced CLI with all features
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## 📄 License

Apache-2.0 License - see LICENSE file for details.

## 🆘 Support

- **Issues**: Report bugs and request features
- **Documentation**: Check examples in `/examples` directory
- **CLI Help**: Run `yenta --help` for command documentation