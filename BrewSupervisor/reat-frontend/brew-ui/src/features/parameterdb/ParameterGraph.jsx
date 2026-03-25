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
import { fetchSources, fetchSourceTypeUi } from './loaders.js';
import { buildGraph, decorateGraph } from './graph/graphModel.js';
import { GraphDetailPanel } from './graph/GraphDetailPanel.jsx';
import { nodeTypes } from './graph/GraphNodes.jsx';

export function ParameterGraph({ fermenterId, params, graph }) {
  const [filter, setFilter] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [sources, setSources] = useState({});
  const [sourceUiByName, setSourceUiByName] = useState({});

  useEffect(() => {
    let cancelled = false;

    async function loadSources() {
      if (!fermenterId) return;
      try {
        const sourceResponse = await fetchSources(fermenterId);
        const nextSources = sourceResponse?.sources ?? {};
        if (cancelled) return;
        setSources(nextSources);

        const uiEntries = await Promise.all(
          Object.entries(nextSources).map(async ([name, record]) => {
            try {
              const response = await fetchSourceTypeUi(fermenterId, record.source_type, name, 'edit');
              return [name, response?.ui ?? null];
            } catch {
              return [name, null];
            }
          }),
        );

        if (!cancelled) setSourceUiByName(Object.fromEntries(uiEntries));
      } catch {
        if (!cancelled) {
          setSources({});
          setSourceUiByName({});
        }
      }
    }

    loadSources();
    return () => {
      cancelled = true;
    };
  }, [fermenterId, params]);

  const { nodes: initialNodes, edges: initialEdges } = useMemo(() => {
    if (!params || !graph) return { nodes: [], edges: [] };

    const needle = filter.trim().toLowerCase();
    const filtered = needle
      ? Object.fromEntries(Object.entries(params).filter(([n]) => n.toLowerCase().includes(needle)))
      : params;

    return buildGraph(filtered, graph, sources, sourceUiByName);
  }, [params, graph, filter, sources, sourceUiByName]);

  const selectedNode = useMemo(
    () => initialNodes.find((node) => node.id === selectedNodeId)?.data ?? null,
    [initialNodes, selectedNodeId],
  );

  const { nodes: decoratedNodes, edges: decoratedEdges } = useMemo(
    () => decorateGraph(initialNodes, initialEdges, selectedNodeId),
    [initialNodes, initialEdges, selectedNodeId],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(decoratedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(decoratedEdges);

  useEffect(() => {
    if (selectedNodeId && !initialNodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(null);
    }
  }, [initialNodes, selectedNodeId]);

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
