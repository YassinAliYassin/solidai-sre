#!/usr/bin/env python3
"""Debug test to understand SSE streaming behavior."""
import json
import logging
import os
import sys
import asyncio

# Must set env vars before importing server
os.environ['CONFIG_SERVICE_URL'] = 'http://localhost:8081'
os.environ['LITELLM_BASE_URL'] = 'http://localhost:4001'
os.environ['NEO4J_URI'] = ''
os.environ['ANTHROPIC_API_KEY'] = ''
os.environ['SOLIDAI_SRE_TENANT_ID'] = 'test-tenant'
os.environ['SOLIDAI_SRE_TEAM_ID'] = 'test-team'
os.environ['OPENROUTER_API_KEY'] = 'test-key'

SRE_AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SRE_AGENT_ROOT)

logging.basicConfig(level=logging.WARNING)

from unittest import mock

PLANNER_RESPONSE = json.dumps({
    'hypotheses': [{'hypothesis': 'Service down', 'priority': 'high', 'agents_to_test': ['kubernetes']}],
    'selected_agents': ['kubernetes'],
    'reasoning': 'test',
})


class MockAIMessage:
    def __init__(self, content='', tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class MockLLM:
    def invoke(self, messages, **kwargs):
        return MockAIMessage(content=PLANNER_RESPONSE)
    def bind_tools(self, tools):
        return self


def _mock_load_team_config():
    m = mock.MagicMock()
    m.raw_config = {
        'agents': {
            'planner': {'prompt': {'system': ''}, 'model': {'name': 'test'}, 'max_iterations': 3},
            'investigation': {'sub_agents': {'kubernetes': True}},
            'writeup': {'prompt': {'system': ''}, 'model': {'name': 'test'}},
        },
        'skills': {'enabled': ['*']},
    }
    return m


def main():
    import importlib
    import server as server_mod

    patches = [
        mock.patch('nodes.init_context.load_team_config', side_effect=_mock_load_team_config),
        mock.patch('nodes.planner.build_llm', return_value=MockLLM()),
        mock.patch('nodes.synthesizer.build_llm', return_value=MockLLM()),
        mock.patch('nodes.writeup.build_llm', return_value=MockLLM()),
        mock.patch('nodes.subagent_executor.build_llm', return_value=MockLLM()),
        mock.patch('nodes.subagent_executor.resolve_tools', return_value=[]),
        mock.patch('nodes.subagent_executor.get_skill_catalog', return_value='No skills.'),
        mock.patch('nodes.subagent_executor.get_skills_for_agent', return_value=['*']),
        mock.patch('nodes.memory_lookup.enhance_investigation_with_memory', side_effect=lambda prompt, **kw: prompt),
        mock.patch('tools.neo4j_semantic_layer.KubernetesGraphTools', side_effect=ImportError('no neo4j')),
        mock.patch('nodes.memory_store.store_investigation_result', return_value=None),
    ]
    for p in patches:
        p.start()

    try:
        importlib.reload(server_mod)
        server_mod._background_tasks.clear()
        server_mod._message_queues.clear()
        server_mod._response_queues.clear()

        # Monkey-patch response_queue to track puts and gets
        _orig_get = asyncio.Queue.get
        _orig_put = asyncio.Queue.put

        queue_log = []

        async def _tracked_get(self):
            item = await _orig_get(self)
            if item is None:
                queue_log.append(('get', 'None', self.qsize()))
            elif isinstance(item, dict):
                queue_log.append(('get', item.get('event', '?'), self.qsize()))
            else:
                queue_log.append(('get', type(item).__name__, self.qsize()))
            return item

        def _tracked_put(self, item):
            if item is None:
                queue_log.append(('put', 'None', self.qsize()))
            elif isinstance(item, dict):
                queue_log.append(('put', item.get('event', '?'), self.qsize()))
            else:
                queue_log.append(('put', type(item).__name__, self.qsize()))
            return _orig_put(self, item)

        asyncio.Queue.get = _tracked_get
        asyncio.Queue.put = _tracked_put

        from starlette.testclient import TestClient
        client = TestClient(server_mod.app)
        response = client.post('/investigate', json={'prompt': 'test'})

        print(f"Response text length: {len(response.text)}")
        print(f"Queue operations ({len(queue_log)}):")
        for op, event_type, qsize in queue_log:
            print(f"  {op}: {event_type} (qsize={qsize})")

        events = []
        for line in response.text.strip().split('\n'):
            line = line.strip()
            if line.startswith('data: '):
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
        print(f"\nEvents in response: {len(events)}")
        for e in events:
            print(f"  type={e.get('type')}")
    finally:
        asyncio.Queue.get = _orig_get
        asyncio.Queue.put = _orig_put
        for p in patches:
            p.stop()


if __name__ == '__main__':
    main()
