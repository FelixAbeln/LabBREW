import dagre from '@dagrejs/dagre';

const NODE_W = 220;
const NODE_H = 72;

const TYPE_COLORS = {
  static: '#3b82f6',
  deadband: '#10b981',
  pid: '#8b5cf6',
  default: '#6b7280',
};

const SOURCE_COLORS = {
  brewtools_kvaser: '#f59e0b',
  modbus_relay: '#ef4444',
  labps3005dn: '#14b8a6',
  digital_twin: '#22c55e',
  system_time: '#eab308',
  default: '#64748b',
};

export function typeColor(t) {
  return TYPE_COLORS[t] ?? TYPE_COLORS.default;
}

export function sourceColor(sourceType) {
  return SOURCE_COLORS[sourceType] ?? SOURCE_COLORS.default;
}

function normalizeStringList(values) {
  const result = [];
  const seen = new Set();
  for (const value of values ?? []) {
    const normalized = String(value ?? '').trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

export function buildSourceInventory(params, sources) {
  const inventory = new Map();

  Object.entries(params ?? {}).forEach(([name, rec]) => {
    const metadata = rec?.metadata ?? {};
    if (metadata?.created_by !== 'data_source') return;
    const owner = String(metadata?.owner ?? '').trim();
    if (!owner) return;

    const sourceRecord = sources?.[owner];
    if (!inventory.has(owner)) {
      inventory.set(owner, {
        name: owner,
        sourceType: String(metadata?.source_type ?? sourceRecord?.source_type ?? 'data_source'),
        device: metadata?.device ? String(metadata.device) : '',
        publishedParams: [],
        publishedCount: 0,
        feedsFrom: normalizeStringList(sourceRecord?.graph?.depends_on),
        sourceRecord: sourceRecord && typeof sourceRecord === 'object' ? sourceRecord : null,
      });
    }

    const entry = inventory.get(owner);
    entry.publishedParams.push(name);
    if (!entry.device && metadata?.device) entry.device = String(metadata.device);
    if (!entry.sourceType && metadata?.source_type) entry.sourceType = String(metadata.source_type);
  });

  Object.entries(sources ?? {}).forEach(([sourceName, sourceRecord]) => {
    if (!inventory.has(sourceName)) {
      inventory.set(sourceName, {
        name: sourceName,
        sourceType: String(sourceRecord?.source_type ?? 'data_source'),
        device: '',
        publishedParams: [],
        publishedCount: 0,
        feedsFrom: normalizeStringList(sourceRecord?.graph?.depends_on),
        sourceRecord: sourceRecord && typeof sourceRecord === 'object' ? sourceRecord : null,
      });
      return;
    }

    const entry = inventory.get(sourceName);
    entry.sourceRecord = sourceRecord && typeof sourceRecord === 'object' ? sourceRecord : entry.sourceRecord;
    entry.feedsFrom = normalizeStringList(sourceRecord?.graph?.depends_on);
    if (sourceRecord?.source_type) entry.sourceType = String(sourceRecord.source_type);
  });

  inventory.forEach((entry) => {
    const feedSet = new Set(entry.feedsFrom);
    if (feedSet.size > 0) {
      entry.publishedParams = entry.publishedParams.filter((paramName) => !feedSet.has(paramName));
    }
    entry.publishedParams.sort((a, b) => a.localeCompare(b));
    entry.publishedCount = entry.publishedParams.length;
  });

  return inventory;
}

function applyLayout(nodes, edges) {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'TB', ranksep: 70, nodesep: 30, marginx: 20, marginy: 20 });

  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => g.setEdge(e.source, e.target, {}, e.id));

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 } };
  });
}

export function buildGraph(params, graph) {
  const deps = graph?.dependencies ?? {};
  const writesMap = graph?.write_targets ?? {};
  const scanOrder = graph?.scan_order ?? [];
  const warnings = graph?.warnings ?? [];
  const sources = graph?.sources ?? {};

  const warnSet = new Set(
    warnings.flatMap((w) => {
      const m = String(w).match(/['"]([^'"]+)['"]/g);
      return m ? m.map((s) => s.replace(/['"]/g, '')) : [];
    }),
  );

  const nodes = Object.entries(params).map(([name, rec]) => ({
    id: name,
    type: 'parameter',
    position: { x: 0, y: 0 },
    data: {
      name,
      paramType: rec.parameter_type ?? 'unknown',
      value: rec.value,
      signalValue: rec.signal_value,
      scanIndex: scanOrder.indexOf(name) >= 0 ? scanOrder.indexOf(name) : null,
      hasWarning: warnSet.has(name),
      invalidConfig: Boolean(rec?.state?.invalid_config),
      config: rec.config,
      state: rec.state,
      metadata: rec.metadata,
    },
  }));

  const sourceInventory = buildSourceInventory(params, sources);
  const sourceNodes = new Map();
  sourceInventory.forEach((entry, sourceName) => {
    sourceNodes.set(sourceName, {
      id: `source:${sourceName}`,
      type: 'source',
      position: { x: 0, y: 0 },
      data: {
        name: sourceName,
        kind: 'source',
        sourceType: entry.sourceType,
        device: entry.device,
        publishedCount: entry.publishedCount,
        publishedParams: [...entry.publishedParams],
        feedsFrom: [...entry.feedsFrom],
      },
    });
  });

  const sourceLinksByName = new Map();
  sourceInventory.forEach((entry, sourceName) => {
    sourceLinksByName.set(sourceName, { feedsFrom: [...entry.feedsFrom] });
  });

  nodes.push(...sourceNodes.values());

  const edges = [];
  for (const [target, depList] of Object.entries(deps)) {
    for (const dep of depList) {
      if (params[dep]) {
        edges.push({
          id: `dep:${dep}→${target}`,
          source: dep,
          target,
          type: 'smoothstep',
          animated: false,
          style: { stroke: '#475569', strokeWidth: 1.5 },
          markerEnd: { type: 'arrowclosed', color: '#475569' },
        });
      }
    }
  }

  for (const [src, targets] of Object.entries(writesMap)) {
    for (const tgt of targets) {
      if (params[tgt]) {
        edges.push({
          id: `wt:${src}→${tgt}`,
          source: src,
          target: tgt,
          type: 'smoothstep',
          animated: true,
          style: { stroke: '#f59e0b', strokeWidth: 1.5, strokeDasharray: '5 3' },
          markerEnd: { type: 'arrowclosed', color: '#f59e0b' },
        });
      }
    }
  }

  sourceInventory.forEach((entry, sourceName) => {
    const ownerColor = sourceColor(entry.sourceType);
    entry.publishedParams.forEach((paramName) => {
      if (!params[paramName] || !sourceNodes.has(sourceName)) return;
      edges.push({
        id: `src:${sourceName}→${paramName}`,
        source: `source:${sourceName}`,
        target: paramName,
        type: 'smoothstep',
        animated: false,
        style: { stroke: ownerColor, strokeWidth: 1.5 },
        markerEnd: { type: 'arrowclosed', color: ownerColor },
      });
    });
  });

  sourceLinksByName.forEach((links, sourceName) => {
    links.feedsFrom.forEach((paramName) => {
      if (!params[paramName] || !sourceNodes.has(sourceName)) return;
      edges.push({
        id: `feed:${paramName}→${sourceName}`,
        source: paramName,
        target: `source:${sourceName}`,
        type: 'smoothstep',
        animated: false,
        style: { stroke: '#38bdf8', strokeWidth: 1.5, strokeDasharray: '4 3' },
        markerEnd: { type: 'arrowclosed', color: '#38bdf8' },
      });
    });
  });

  return { nodes: applyLayout(nodes, edges), edges };
}

function collectLineage(edgeList, startId) {
  if (!startId) return { nodes: new Set(), edges: new Set() };

  const incoming = new Map();
  const outgoing = new Map();

  edgeList.forEach((edge) => {
    if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
    if (!incoming.has(edge.target)) incoming.set(edge.target, []);
    outgoing.get(edge.source).push(edge);
    incoming.get(edge.target).push(edge);
  });

  const nodeIds = new Set([startId]);
  const edgeIds = new Set();

  function walk(adjacency, nextKey) {
    const queue = [startId];
    const seen = new Set([startId]);

    while (queue.length > 0) {
      const current = queue.shift();
      for (const edge of adjacency.get(current) ?? []) {
        edgeIds.add(edge.id);
        nodeIds.add(edge.source);
        nodeIds.add(edge.target);
        const next = nextKey(edge);
        if (!seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
  }

  walk(incoming, (edge) => edge.source);
  walk(outgoing, (edge) => edge.target);

  return { nodes: nodeIds, edges: edgeIds };
}

export function decorateGraph(nodes, edges, selectedNodeId) {
  if (!selectedNodeId) return { nodes, edges };

  const lineage = collectLineage(edges, selectedNodeId);

  return {
    nodes: nodes.map((node) => {
      const isSelected = node.id === selectedNodeId;
      const isRelated = lineage.nodes.has(node.id);
      return {
        ...node,
        selected: isSelected,
        zIndex: isSelected ? 3 : isRelated ? 2 : 1,
        data: {
          ...node.data,
          isSelected,
          isRelated,
          isDimmed: !isRelated,
        },
      };
    }),
    edges: edges.map((edge) => {
      const isRelated = lineage.edges.has(edge.id);
      const baseStyle = edge.style ?? {};
      const baseLabelStyle = edge.labelStyle ?? {};
      return {
        ...edge,
        animated: isRelated ? edge.animated : false,
        zIndex: isRelated ? 2 : 0,
        style: {
          ...baseStyle,
          opacity: isRelated ? 1 : 0.12,
          strokeWidth: isRelated
            ? Math.max(baseStyle.strokeWidth ?? 1.5, 2.5)
            : Math.max((baseStyle.strokeWidth ?? 1.5) - 0.5, 1),
        },
        labelStyle: {
          ...baseLabelStyle,
          opacity: isRelated ? 1 : 0.25,
        },
      };
    }),
  };
}
