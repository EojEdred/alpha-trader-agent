"""
Workflow Orchestrator - Executes workflow DAGs

Implements A2rchitech scientific loop phases:
OBSERVE -> THINK -> PLAN -> BUILD -> EXECUTE -> VERIFY -> LEARN
"""

import asyncio
import importlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import yaml
from loguru import logger


@dataclass
class WorkflowResult:
    """Result of a workflow execution."""
    workflow_id: str
    status: str  # 'success', 'failed', 'partial'
    start_time: datetime
    end_time: datetime
    results: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ExecutionContext:
    """Shared context across workflow nodes."""
    data: Dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any):
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def clear(self):
        self.data.clear()


class WorkflowOrchestrator:
    """Executes workflows defined in YAML."""

    def __init__(self, config):
        self.config = config
        self.workflows: Dict[str, dict] = {}
        self.tools: Dict[str, dict] = {}
        self.context = ExecutionContext()
        self._initialized = False

    async def initialize(self):
        """Load workflows and tools."""
        if self._initialized:
            return

        base_path = Path(__file__).parent.parent

        # Load workflows
        workflows_dir = base_path / 'workflows'
        if workflows_dir.exists():
            for wf_file in workflows_dir.glob('*.yaml'):
                try:
                    wf_data = yaml.safe_load(wf_file.read_text())
                    wf = wf_data['workflow']
                    self.workflows[wf['id']] = wf
                    logger.info(f"Loaded workflow: {wf['id']}")
                except Exception as e:
                    logger.error(f"Failed to load workflow {wf_file}: {e}")

        # Load tools
        tools_file = base_path / 'tools' / 'tool_registry.yaml'
        if tools_file.exists():
            try:
                tools_data = yaml.safe_load(tools_file.read_text())
                for tool in tools_data.get('tools', []):
                    self.tools[tool['id']] = tool
                logger.info(f"Loaded {len(self.tools)} tools")
            except Exception as e:
                logger.error(f"Failed to load tools: {e}")

        self._initialized = True

    async def execute_workflow(self, workflow_id: str) -> WorkflowResult:
        """Execute a workflow by ID."""
        if workflow_id not in self.workflows:
            raise ValueError(f"Unknown workflow: {workflow_id}")

        workflow = self.workflows[workflow_id]
        logger.info(f"Starting workflow: {workflow['name']}")

        start_time = datetime.utcnow()
        results = {}
        self.context.clear()

        try:
            # Build execution order from DAG
            execution_order = self._topological_sort(workflow)
            logger.debug(f"Execution order: {execution_order}")

            for node_id in execution_order:
                node = self._get_node(workflow, node_id)

                # Check edge conditions
                if not self._check_conditions(workflow, node_id):
                    logger.debug(f"Skipping node {node_id} due to condition")
                    continue

                logger.info(f"Executing: {node['name']} (phase: {node['phase']})")

                # Gather inputs from context
                inputs = self._gather_inputs(node)

                # Execute node
                try:
                    node_result = await self._execute_node(node, inputs)
                    results[node_id] = node_result

                    # Store outputs in context
                    outputs = node.get('outputs', [])
                    if not outputs:
                        continue

                    if isinstance(node_result, dict):
                        # If tool returned a wrapped non-dict result: {'result': val}
                        # and node expects a single output, map it directly
                        if len(outputs) == 1 and 'result' in node_result and len(node_result) == 1:
                            self.context.set(outputs[0], node_result['result'])
                        else:
                            # Standard dict mapping
                            for output in outputs:
                                if output in node_result:
                                    self.context.set(output, node_result[output])
                                else:
                                    # Fallback: set the whole dict if name not found
                                    self.context.set(output, node_result)
                    else:
                        # Non-dict result (should have been wrapped by _execute_node but just in case)
                        if len(outputs) == 1:
                            self.context.set(outputs[0], node_result)

                except Exception as e:
                    logger.error(f"Node {node_id} failed: {e}")
                    results[node_id] = {'error': str(e)}
                    # Continue with other nodes unless critical

            return WorkflowResult(
                workflow_id=workflow_id,
                status='success',
                start_time=start_time,
                end_time=datetime.utcnow(),
                results=results
            )

        except Exception as e:
            logger.error(f"Workflow {workflow_id} failed: {e}")
            return WorkflowResult(
                workflow_id=workflow_id,
                status='failed',
                start_time=start_time,
                end_time=datetime.utcnow(),
                results=results,
                error=str(e)
            )

    def _topological_sort(self, workflow: dict) -> List[str]:
        """Sort nodes in execution order respecting dependencies."""
        nodes = {n['id']: n for n in workflow['nodes']}
        edges = workflow.get('edges', [])

        # Build adjacency list and in-degree count
        in_degree = {n: 0 for n in nodes}
        graph = {n: [] for n in nodes}

        for edge in edges:
            from_node = edge['from']
            to_node = edge['to']
            if from_node in graph and to_node in in_degree:
                graph[from_node].append(to_node)
                in_degree[to_node] += 1

        # Kahn's algorithm for topological sort
        queue = [n for n in nodes if in_degree[n] == 0]
        result = []

        while queue:
            # Sort by phase order for consistent execution
            phase_order = ['Observe', 'Think', 'Plan', 'Build', 'Execute', 'Verify', 'Learn']
            queue.sort(key=lambda x: phase_order.index(nodes[x].get('phase', 'Execute')))

            node = queue.pop(0)
            result.append(node)

            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(nodes):
            logger.warning("Workflow has circular dependencies")
            # Add remaining nodes
            for n in nodes:
                if n not in result:
                    result.append(n)

        return result

    def _get_node(self, workflow: dict, node_id: str) -> dict:
        """Get node by ID."""
        for node in workflow['nodes']:
            if node['id'] == node_id:
                return node
        raise ValueError(f"Node not found: {node_id}")

    def _check_conditions(self, workflow: dict, node_id: str) -> bool:
        """Check if edge conditions are met for a node."""
        edges = workflow.get('edges', [])

        for edge in edges:
            if edge['to'] == node_id and 'condition' in edge:
                condition = edge['condition']
                # Simple condition evaluation
                # e.g., "stop_triggers.length > 0"
                try:
                    # Extract variable and check in context
                    if '.length > 0' in condition:
                        var_name = condition.split('.')[0]
                        value = self.context.get(var_name, [])
                        if not (isinstance(value, list) and len(value) > 0):
                            return False
                    elif '== true' in condition:
                        var_name = condition.split(' ')[0]
                        # Handle dot notation: compliance_status.can_trade
                        if '.' in var_name:
                            parts = var_name.split('.')
                            obj = self.context.get(parts[0], {})
                            for part in parts[1:]:
                                if isinstance(obj, dict):
                                    obj = obj.get(part, False)
                                else:
                                    obj = False
                                    break
                            if not obj:
                                return False
                        elif not self.context.get(var_name, False):
                            return False
                    elif '!= null' in condition:
                        var_name = condition.split(' ')[0]
                        if self.context.get(var_name) is None:
                            return False
                    elif '== null' in condition:
                        var_name = condition.split(' ')[0]
                        if self.context.get(var_name) is not None:
                            return False
                except Exception as e:
                    logger.warning(f"Condition evaluation failed: {e}")

        return True

    def _gather_inputs(self, node: dict) -> dict:
        """Gather inputs from context and node parameters."""
        inputs = {}
        
        # 1. Get static parameters from node definition
        if 'parameters' in node:
            inputs.update(node['parameters'])
            
        # 2. Get dynamic inputs from execution context
        for input_name in node.get('inputs', []):
            value = self.context.get(input_name)
            if value is not None:
                inputs[input_name] = value

        # 3. Add global config
        inputs['config'] = self.config

        return inputs

    async def _execute_node(self, node: dict, inputs: dict) -> dict:
        """Execute a single workflow node."""
        tool_id = node.get('skill_id')

        if tool_id and tool_id in self.tools:
            tool = self.tools[tool_id]
            impl_path = tool.get('implementation', {}).get('standalone')

            if impl_path:
                try:
                    # Parse implementation path: "tools.market_data::fetch_options_chain"
                    module_path, func_name = impl_path.split('::')

                    # Import module
                    module = importlib.import_module(module_path)
                    func = getattr(module, func_name)
                except (ModuleNotFoundError, AttributeError) as e:
                    logger.warning(f"Tool implementation not found for {tool_id}: {e}")
                    return {'status': 'skipped', 'reason': 'implementation_not_found'}

                # Execute
                try:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(**inputs)
                    else:
                        result = func(**inputs)

                    return result if isinstance(result, dict) else {'result': result}
                except Exception as e:
                    logger.error(f"Tool {tool_id} execution failed: {e}")
                    raise

        # No implementation - return placeholder
        logger.debug(f"No implementation for tool: {tool_id}")
        return {'status': 'placeholder', 'node': node['id']}

    async def shutdown(self):
        """Clean shutdown."""
        logger.info("Orchestrator shutting down")
        self.context.clear()
