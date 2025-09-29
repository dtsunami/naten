# da_code Development Guide & Achievements

This file provides guidance to Claude Code when working with this codebase and documents our successful implementations.

## ✅ MAJOR ACHIEVEMENT: Dynamic MCP Architecture (October 2025)

We have successfully implemented a **revolutionary dynamic MCP server integration** that enables:

### 🚀 **Cross-Platform Agent Tool Expansion**
- **Windows ↔ Linux**: Seamless tool access across different machines
- **On-demand tools**: Add capabilities without agent restart
- **Session-scoped**: Clean, temporary integration (no persistent config pollution)
- **One-command setup**: Copy/paste JSON config and immediately gain new tools

### 📋 **Clipboard MCP Servers (Clippy & ClipJS)**

**Location**: `/mcp/clippy/` (Python) and `/mcp/clipjs/` (Node.js)

**Tools Available**:
- `read_text` - Read text from Windows clipboard
- `read_image` - Read images from Windows clipboard as base64
- `write_text` - Write text to Windows clipboard
- `write_image` - Write base64 images to Windows clipboard

**Usage Flow**:
1. **Windows**: `clippy` or `clipjs` → Auto-copies connection command
2. **Linux da_code**: Paste command → `add_mcp {"name":"clipboard",...}`
3. **Agent**: Immediately gains `clipboard_read_text`, `clipboard_write_text`, etc.
4. **Magic**: Cross-platform clipboard access from Linux agent to Windows machine!

### 🔧 **Technical Implementation**

**Key Files Modified**:
- `/da_code/async_agent.py` - Added `_create_mcps()` and `_create_mcp_tool()` methods
- `/da_code/cli.py` - Added `add_mcp` command with JSON parsing and session integration
- `/da_code/tools.py` - Enhanced tool suite (removed redundant mcp_connect tool)

**MCP Tool Integration**:
```python
# In async_agent.py _create_tools()
mcp_tools = self._create_mcps()  # Load from session.mcp_servers
tools.update(mcp_tools)          # Add to agent's tool dictionary

# Tools named as: {server_name}_{tool_name}
# Example: clipboard_read_text, clipboard_write_image
```

**Async Event Loop Handling**:
- Fixed `asyncio.run()` conflicts in running event loops
- Used `ThreadPoolExecutor` for proper async-to-sync tool execution
- Maintains clean async architecture throughout

## Current State: Production-Ready Foundation ✅

We have successfully established:
- **Async LangChain agents** with real-time status monitoring
- **PostgreSQL chat memory** with proper persistence
- **Rich CLI interface** with clean startup and execution
- **Unified telemetry** via MongoDB tracking
- **Dynamic MCP server integration** 🔥 **NEW!**
- **Cross-platform tool access** 🔥 **NEW!**
- **python-dotenv** configuration with variable substitution
- **Clean architecture** with proper separation of concerns

## Agno Integration Philosophy

**Incremental & Test-Driven**: Small, focused changes that build on existing patterns
**Performance Enhancement**: Add Agno for speed while keeping LangChain for reasoning
**Pythonic Approach**: Clean, maintainable code following established patterns
**Unified Experience**: Same CLI, same memory, same monitoring - just faster execution

---

## Phase 1: Foundation & Research (Week 1)
*Goal: Understand Agno and create minimal integration without breaking existing functionality*

### Task 1.1: Agno Research & Setup
- [ ] Install Agno in development environment: `pip install agno`
- [ ] Create `tests/test_agno_basic.py` - basic Agno agent creation test
- [ ] Document Agno capabilities and API in `docs/agno_research.md`
- [ ] Verify Agno works with our Azure OpenAI configuration

**Acceptance Criteria:**
- Agno installed and basic agent can be created
- Test passes showing Agno agent responds to simple prompts
- No impact on existing LangChain functionality

### Task 1.2: Pydantic Models for Agno Tracking
```python
# Add to models.py
class AgnoAgentExecution(BaseModel):
    """Track Agno agent execution metrics."""
    agent_name: str
    framework: str = "agno"
    task_type: str
    execution_time_ms: float
    memory_usage_kb: float
    token_count: int
    success: bool
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class FrameworkMetrics(BaseModel):
    """Compare performance between frameworks."""
    framework: str
    total_executions: int
    avg_execution_time_ms: float
    total_tokens: int
    success_rate: float
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

**Acceptance Criteria:**
- Models added to `models.py` following existing patterns
- MongoDB can store Agno execution data
- Test coverage for new models

### Task 1.3: Minimal Agno Agent Class
```python
# Create da_code/agno_agents.py
class AgnoAgentWrapper:
    """Wrapper for Agno agents that integrates with our telemetry."""

    def __init__(self, name: str, instructions: str, config: AgentConfig):
        self.name = name
        self.config = config
        self.agno_agent = self._create_agno_agent(instructions)
        self.telemetry = da_mongo

    async def execute(self, task: str) -> str:
        """Execute task with telemetry tracking."""
        start_time = time.time()
        try:
            result = await self.agno_agent.arun(task)
            await self._track_execution(task, time.time() - start_time, True)
            return result
        except Exception as e:
            await self._track_execution(task, time.time() - start_time, False, str(e))
            raise
```

**Acceptance Criteria:**
- Single Agno agent can be created and executed
- Execution tracked in MongoDB with consistent format
- Error handling follows existing patterns
- Test coverage for wrapper class

---

## Phase 2: Integration Layer (Week 2)
*Goal: Create unified interface without changing CLI behavior*

### Task 2.1: Agent Framework Abstraction
```python
# Add to da_code/agent_framework.py
class AgentFramework(Enum):
    LANGCHAIN = "langchain"
    AGNO = "agno"

class UnifiedAgentInterface:
    """Abstract interface for both agent frameworks."""

    async def execute_task(self, task: str) -> str:
        """Execute a task - implementation specific."""
        raise NotImplementedError

    def get_framework_name(self) -> str:
        """Return framework identifier."""
        raise NotImplementedError

    async def get_metrics(self) -> Dict[str, Any]:
        """Get execution metrics."""
        raise NotImplementedError
```

**Acceptance Criteria:**
- Clean abstraction that both frameworks can implement
- No changes to existing CLI or user experience
- LangChain agent implements interface without modification
- Test coverage for interface contract

### Task 2.2: Simple Task Router
```python
# Add to da_code/task_router.py
class TaskRouter:
    """Route tasks to appropriate framework."""

    def __init__(self):
        self.routing_rules = {
            'default': AgentFramework.LANGCHAIN,  # Safe default
            'keywords': {
                'lint': AgentFramework.AGNO,      # Future: when implemented
                'format': AgentFramework.AGNO,    # Future: when implemented
            }
        }

    def route_task(self, task: str) -> AgentFramework:
        """Determine which framework should handle task."""
        # Phase 2: Always route to LangChain (no behavior change)
        # Phase 3+: Add intelligent routing
        return AgentFramework.LANGCHAIN
```

**Acceptance Criteria:**
- Router exists but doesn't change current behavior
- All tasks still go to LangChain (zero risk)
- Foundation for future smart routing
- Test coverage for routing logic

### Task 2.3: Enhanced Status Interface
```python
# Extend cli.py SimpleStatusInterface
class HybridStatusInterface(SimpleStatusInterface):
    """Status interface that can track multiple frameworks."""

    def __init__(self):
        super().__init__()
        self.framework_metrics = {
            'langchain': {'calls': 0, 'tokens': 0},
            'agno': {'calls': 0, 'tokens': 0}
        }

    def track_framework_call(self, framework: str, tokens: int = 0):
        """Track calls from specific framework."""
        if framework in self.framework_metrics:
            self.framework_metrics[framework]['calls'] += 1
            self.framework_metrics[framework]['tokens'] += tokens
```

**Acceptance Criteria:**
- Status interface ready for multi-framework tracking
- No changes to current display (same user experience)
- Foundation for showing framework breakdown
- Backward compatible with existing status

---

## Phase 3: Agno Agent Pool (Week 3)
*Goal: Add fast Agno agents for specific tasks*

### Task 3.1: Single Agno Specialist Agent
```python
# Create first production Agno agent
class AgnoCodeLinter(AgnoAgentWrapper):
    """Fast code linting agent using Agno."""

    def __init__(self, config: AgentConfig):
        instructions = """You are a fast code linter. Quickly identify:
        - Syntax errors
        - Style violations
        - Import issues
        - Basic code smells
        Respond concisely with specific line numbers and fixes."""

        super().__init__("CodeLinter", instructions, config)
```

**Acceptance Criteria:**
- Single Agno agent for linting tasks
- Measurably faster than LangChain equivalent
- Same quality output as LangChain
- Comprehensive test suite comparing both approaches

### Task 3.2: Task Classification & Routing
```python
# Update TaskRouter with real routing logic
def route_task(self, task: str) -> AgentFramework:
    """Intelligent task routing."""
    task_lower = task.lower()

    # Route to Agno for specific quick tasks
    agno_keywords = ['lint', 'check syntax', 'format code', 'style check']
    if any(keyword in task_lower for keyword in agno_keywords):
        return AgentFramework.AGNO

    # Route to LangChain for everything else (reasoning, conversation)
    return AgentFramework.LANGCHAIN
```

**Acceptance Criteria:**
- Intelligent routing based on task content
- A/B testing shows Agno faster for designated tasks
- LangChain still handles complex reasoning
- User can override with command flags if needed

### Task 3.3: Unified Agent Manager
```python
# Add to da_code/hybrid_agents.py
class HybridAgentManager:
    """Manages both LangChain and Agno agents."""

    def __init__(self, config: AgentConfig, session: CodeSession):
        self.config = config
        self.session = session
        self.router = TaskRouter()

        # Initialize both frameworks
        self.langchain_agent = DaCodeAgent(config, session)
        self.agno_agents = {
            'linter': AgnoCodeLinter(config),
            # Add more as we build them
        }

    async def execute_task(self, task: str) -> str:
        """Route task to appropriate framework."""
        framework = self.router.route_task(task)

        if framework == AgentFramework.AGNO:
            agent_name = self._select_agno_agent(task)
            return await self.agno_agents[agent_name].execute(task)
        else:
            return await self.langchain_agent.chat(task)
```

**Acceptance Criteria:**
- Seamless routing between frameworks
- Performance metrics show improvement for routed tasks
- No degradation in user experience
- Comprehensive integration tests

---

## Phase 4: CLI Enhancement (Week 4)
*Goal: Expose framework choice to users while maintaining simplicity*

### Task 4.1: Enhanced CLI Options
```bash
# New CLI options (backward compatible)
da_code "review this code"                    # Auto-routing
da_code --agent auto "best approach"          # Smart selection
da_code --agent agno "quick lint check"       # Force Agno
da_code --agent langchain "explain design"    # Force LangChain
da_code --performance                          # Show framework metrics
```

**Acceptance Criteria:**
- All existing commands work unchanged
- New options provide framework control
- Performance command shows useful metrics
- Help text clearly explains options

### Task 4.2: Enhanced Status Display
```
✅ Complete | 0.8s | Ready | 🤖 gpt-5-chat | 💾 PostgreSQL | 🍃 Connected
⚡ Agno: 3 agents (avg: 0.05s) | 🦜 LangChain: 1 agent (avg: 1.2s) | 🎯 Auto-routing
```

**Acceptance Criteria:**
- Status shows framework breakdown
- Performance comparison visible
- Clean, informative display
- Updates in real-time during execution

### Task 4.3: Performance Benchmarking
```python
# Add to da_code/benchmarks.py
class FrameworkBenchmark:
    """Compare framework performance for different task types."""

    async def benchmark_task_type(self, task_type: str, iterations: int = 10):
        """Benchmark both frameworks on same task type."""
        agno_times = []
        langchain_times = []

        # Run same task on both frameworks, measure performance
        # Store results in MongoDB for analysis
```

**Acceptance Criteria:**
- Automated benchmarking of both frameworks
- Performance data stored and queryable
- Reports show where each framework excels
- Guides future routing improvements

---

## Phase 5: Advanced Multi-Agent Workflows (Week 5+)
*Goal: Leverage Agno's speed for parallel task execution*

### Task 5.1: Parallel Agent Execution
```python
async def comprehensive_code_analysis(self, code: str):
    """Use multiple Agno agents in parallel for fast analysis."""

    # Run multiple fast analyses in parallel
    tasks = [
        self.agno_agents['linter'].execute(f"Lint: {code}"),
        self.agno_agents['security'].execute(f"Security scan: {code}"),
        self.agno_agents['performance'].execute(f"Performance check: {code}"),
    ]

    results = await asyncio.gather(*tasks)

    # Use LangChain to synthesize results with reasoning
    synthesis = await self.langchain_agent.chat(f"""
    Analyze these code reviews and provide comprehensive assessment:
    {chr(10).join(results)}
    """)

    return synthesis
```

**Acceptance Criteria:**
- Multiple Agno agents execute in parallel
- LangChain synthesizes results with reasoning
- Total time faster than sequential execution
- Quality maintained or improved

---

## Development Principles

### Code Quality Standards
- **Pythonic**: Follow PEP 8, use type hints, leverage Python idioms
- **Testable**: Every feature has comprehensive tests
- **Maintainable**: Clear separation of concerns, minimal coupling
- **Observable**: Rich telemetry and logging for debugging

### Pydantic Model Guidelines
- **All models in models.py**: Centralized data structures
- **MongoDB integration**: Consistent field naming and validation
- **Version compatibility**: Handle schema evolution gracefully
- **Performance**: Efficient serialization for high-frequency operations

### Integration Testing Strategy
- **Backward compatibility**: Existing functionality never breaks
- **Performance regression**: Monitor execution times continuously
- **Error handling**: Graceful degradation when frameworks fail
- **Memory usage**: Track and optimize resource consumption

### Success Metrics
- **Performance**: Measureable speed improvement for quick tasks
- **Quality**: Same or better output quality compared to LangChain-only
- **Reliability**: No increase in error rates or failures
- **User Experience**: CLI remains simple and intuitive

---

## Risk Mitigation

### Technical Risks
- **Framework conflicts**: Isolate frameworks, careful dependency management
- **Memory issues**: Monitor resource usage, implement circuit breakers
- **API changes**: Pin versions, test upgrades in isolation

### Product Risks
- **Complexity creep**: Maintain simple CLI interface, hide implementation
- **Performance regression**: Continuous benchmarking, rollback capability
- **User confusion**: Clear documentation, sensible defaults

### Rollback Strategy
- **Feature flags**: Disable Agno integration if issues arise
- **Gradual rollout**: Start with non-critical tasks, expand carefully
- **Monitoring**: Alert on performance or error rate changes

---

This roadmap ensures we build on our solid foundation while incrementally adding Agno's performance benefits. Each phase delivers value while maintaining the quality and reliability users expect from da_code.