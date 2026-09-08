import type { NodePosition } from '../types';

interface ObjectTreeProps {
  nodes: NodePosition[];
  selected: NodePosition | null;
  onSelect: (node: NodePosition) => void;
}

function NodeButton({ node, selected, onSelect, accent = false }: { node: NodePosition; selected: boolean; onSelect: (node: NodePosition) => void; accent?: boolean }) {
  const prefix = node.nodeType === 'SATELLITE' ? 'SAT' : 'GS';
  return <button type="button" className={`tree-node ${selected ? 'selected' : ''} ${accent ? 'compute' : ''}`} onClick={() => onSelect(node)}><span className="node-icon">{node.nodeType === 'SATELLITE' ? '◆' : '▲'}</span>{prefix}-{node.nodeId}<span className="node-health" /></button>;
}

export function ObjectTree({ nodes, selected, onSelect }: ObjectTreeProps) {
  const satellites = nodes.filter((node) => node.nodeType === 'SATELLITE');
  const stations = nodes.filter((node) => node.nodeType === 'GROUND_STATION');
  const compute = satellites.filter((node) => [0, 3, 7].includes(node.nodeId));
  return (
    <aside className="panel object-tree">
      <div className="panel-title"><span>객체 탐색기</span><small>{nodes.length} 객체</small></div>
      <section><h2><span>⌄</span> 위성 <em>{satellites.length}</em></h2><div className="tree-list">{satellites.map((node) => <NodeButton key={node.nodeId} node={node} selected={selected?.nodeType === node.nodeType && selected.nodeId === node.nodeId} onSelect={onSelect} />)}</div></section>
      <section><h2><span>⌄</span> 지상국 <em>{stations.length}</em></h2><div className="tree-list">{stations.map((node) => <NodeButton key={node.nodeId} node={node} selected={selected?.nodeType === node.nodeType && selected.nodeId === node.nodeId} onSelect={onSelect} />)}</div></section>
      <section className="compute-section"><h2><span>⌄</span> 연산 노드 <em>{compute.length}</em></h2><div className="tree-list">{compute.map((node) => <NodeButton key={node.nodeId} node={node} selected={selected?.nodeType === node.nodeType && selected.nodeId === node.nodeId} onSelect={onSelect} accent />)}</div></section>
    </aside>
  );
}
