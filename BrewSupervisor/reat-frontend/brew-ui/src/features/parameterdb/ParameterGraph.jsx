import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { buildGraph, decorateGraph } from './graph/graphModel.js';
import { GraphDetailPanel } from './graph/GraphDetailPanel.jsx';
import { nodeTypes } from './graph/graphNodeTypes.js';

function buildReverseLinks(linkMap) {
  const reverse = new Map();
  Object.entries(linkMap ?? {}).forEach(([from, toList]) => {
    (toList ?? []).forEach((to) => {
      if (!reverse.has(to)) reverse.set(to, []);
      reverse.get(to).push(from);
    });
  });
  return reverse;
}

function expandFilteredParams(params, graph, needle) {
  if (!needle) return params;

  const entries = Object.entries(params ?? {});
  const matched = entries
    .filter(([name]) => name.toLowerCase().includes(needle))
    .map(([name]) => name);

  if (matched.length === 0) return {};

  const deps = graph?.dependencies ?? {};
  const writes = graph?.write_targets ?? {};
  const reverseDeps = buildReverseLinks(deps);
  const reverseWrites = buildReverseLinks(writes);
  const visible = new Set(matched);

  matched.forEach((name) => {
    (deps[name] ?? []).forEach((dep) => visible.add(dep));
    (writes[name] ?? []).forEach((target) => visible.add(target));
    (reverseDeps.get(name) ?? []).forEach((candidate) => visible.add(candidate));
    (reverseWrites.get(name) ?? []).forEach((candidate) => visible.add(candidate));
  });

  return Object.fromEntries(entries.filter(([name]) => visible.has(name)));
}

export function ParameterGraph({ params, graph }) {
  const [filter, setFilter] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState(null);

  const { nodes: initialNodes, edges: initialEdges } = useMemo(() => {
    if (!params || !graph) return { nodes: [], edges: [] };

    const needle = filter.trim().toLowerCase();
    const filtered = expandFilteredParams(params, graph, needle);

    return buildGraph(filtered, graph);
  }, [params, graph, filter]);

  const activeSelectedNodeId = useMemo(
    () => (selectedNodeId && initialNodes.some((node) => node.id === selectedNodeId) ? selectedNodeId : null),
    [initialNodes, selectedNodeId],
  );

  const selectedNode = useMemo(
    () => initialNodes.find((node) => node.id === activeSelectedNodeId)?.data ?? null,
    [activeSelectedNodeId, initialNodes],
  );

  const { nodes: decoratedNodes, edges: decoratedEdges } = useMemo(
    () => decorateGraph(initialNodes, initialEdges, activeSelectedNodeId),
    [activeSelectedNodeId, initialEdges, initialNodes],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(decoratedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(decoratedEdges);

  useEffect(() => {
    setNodes(decoratedNodes);
    setEdges(decoratedEdges);
  }, [decoratedNodes, decoratedEdges, setEdges, setNodes]);

  const onNodeClick = useCallback((_evt, node) => {
    setSelectedNodeId(node.id);
  }, []);

  return (
    <div className="pdb-graph-container">
      <div className="pdb-graph-toolbar">
        <input
          className="pdb-input pdb-graph-filter"
          placeholder="Filter parameters..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <span style={{ fontSize: 12, color: '#64748b' }}>{nodes.length} nodes</span>
        <span style={{ fontSize: 12, color: '#475569' }}>Click a node to trace its full lineage</span>
        <div className="pdb-graph-legend">
          <span className="pdb-legend-item" style={{ '--lc': '#475569' }}>dependency</span>
          <span className="pdb-legend-item pdb-legend-dashed" style={{ '--lc': '#38bdf8' }}>source dependency</span>
          <span className="pdb-legend-item pdb-legend-dashed" style={{ '--lc': '#f59e0b' }}>writes</span>
        </div>
      </div>

      <div className="pdb-graph-body">
        <div className="pdb-graph-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            edgesFocusable={false}
            edgesReconnectable={false}
            connectOnClick={false}
            panOnDrag
            zoomOnDoubleClick={false}
            deleteKeyCode={null}
            fitView
            fitViewOptions={{ padding: 0.15 }}
            minZoom={0.1}
            proOptions={{ hideAttribution: true }}
            colorMode="dark"
          >
            <Controls />
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#1e293b" />
          </ReactFlow>
        </div>

        <GraphDetailPanel selected={selectedNode} graph={graph} onClear={() => setSelectedNodeId(null)} />
      </div>
    </div>
  );
}
