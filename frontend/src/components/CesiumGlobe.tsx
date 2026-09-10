import { useEffect, useRef } from 'react';
import { Cartesian2, Cartesian3, Color, ConstantPositionProperty, ConstantProperty, Entity, HeightReference, ImageryLayer, OpenStreetMapImageryProvider, PolylineDashMaterialProperty, ScreenSpaceEventHandler, ScreenSpaceEventType, Viewer } from 'cesium';
import type { DisplayOptions, FailedLinkSelection, Link, NodePosition } from '../types';

interface Props {
  computeNodeId: number | null; nodes: NodePosition[]; selected: NodePosition | null; normalLinks: Link[]; route: number[]; failedLinks: Link[]; recoveredLinks: Link[];
  unavailableNodeIds: Set<number>; options: DisplayOptions; onSelect: (node: NodePosition) => void; onFailedLinkSelect: (link: FailedLinkSelection) => void;
}
const keyOf = (node: NodePosition) => `${node.nodeType}-${node.nodeId}`;
const linkKey = ([from, to]: Link) => `${Math.min(from, to)}-${Math.max(from, to)}`;

export function CesiumGlobe({ computeNodeId, nodes, selected, normalLinks, route, failedLinks, recoveredLinks, unavailableNodeIds, options, onSelect, onFailedLinkSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Viewer>();
  const nodeEntities = useRef(new Map<string, Entity>());
  const nodesRef = useRef(nodes); const selectRef = useRef(onSelect); const failedSelectRef = useRef(onFailedLinkSelect);
  nodesRef.current = nodes; selectRef.current = onSelect; failedSelectRef.current = onFailedLinkSelect;

  useEffect(() => {
    if (!containerRef.current) return;
    const viewer = new Viewer(containerRef.current, {
      baseLayer: new ImageryLayer(new OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org/' })), terrainProvider: undefined,
      animation: false, timeline: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
      navigationHelpButton: false, fullscreenButton: false, infoBox: false, selectionIndicator: false,
    });
    viewer.scene.globe.baseColor = Color.fromCssColorString('#071826'); viewer.scene.backgroundColor = Color.fromCssColorString('#03080d');
    viewer.camera.setView({ destination: Cartesian3.fromDegrees(115, 25, 18_000_000) });
    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((event: { position: Cartesian2 }) => {
      const id = viewer.scene.pick(event.position)?.id;
      if (!(id instanceof Entity)) return;
      if (id.id.startsWith('failed:')) {
        const [from, to] = id.id.slice(7).split('-').map(Number); failedSelectRef.current({ from, to }); return;
      }
      const node = nodesRef.current.find((candidate) => keyOf(candidate) === id.id); if (node) selectRef.current(node);
    }, ScreenSpaceEventType.LEFT_CLICK);
    viewerRef.current = viewer;
    return () => { handler.destroy(); viewer.destroy(); viewerRef.current = undefined; nodeEntities.current.clear(); };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current; if (!viewer) return;
    const currentKeys = new Set(nodes.map(keyOf));
    for (const [key, entity] of nodeEntities.current) entity.show = currentKeys.has(key);
    nodes.forEach((node) => {
      const key = keyOf(node); const compute = node.nodeType === 'SATELLITE' && [0, 3, 7].includes(node.nodeId); const station = node.nodeType === 'GROUND_STATION';
      const unavailable = unavailableNodeIds.has(node.nodeId); const position = Cartesian3.fromDegrees(node.longitudeDeg, node.latitudeDeg, node.altitudeM);
      let entity = nodeEntities.current.get(key);
      if (!entity) {
        entity = viewer.entities.add({ id: key, position, point: { pixelSize: compute ? 16 : station ? 11 : 8, outlineWidth: compute ? 3 : 2, heightReference: HeightReference.NONE, disableDepthTestDistance: Number.POSITIVE_INFINITY }, label: { text: `${station ? 'GS' : 'SAT'}-${node.nodeId}`, font: '11px Inter, sans-serif', fillColor: Color.WHITE, showBackground: true, backgroundColor: Color.fromCssColorString('#09131dcc'), pixelOffset: new Cartesian2(0, -22), disableDepthTestDistance: Number.POSITIVE_INFINITY } });
        nodeEntities.current.set(key, entity);
      } else (entity.position as ConstantPositionProperty).setValue(position);
      entity.show = true;
      if (entity.point) { entity.point.color = new ConstantProperty(unavailable ? Color.RED : compute ? Color.fromCssColorString('#f7b955') : station ? Color.fromCssColorString('#40dfb1') : Color.fromCssColorString('#54a8ff')); entity.point.outlineColor = new ConstantProperty(unavailable ? Color.fromCssColorString('#ffb0b0') : Color.fromCssColorString('#06131e')); }
      if (entity.point && node.nodeId === computeNodeId) entity.point.outlineColor = new ConstantProperty(Color.YELLOW);
      if (entity.label) {
        entity.label.show = new ConstantProperty(options.nodeLabels || node.nodeId === computeNodeId);
        entity.label.text = new ConstantProperty(`${station ? 'GS' : 'SAT'}-${node.nodeId}${node.nodeId === computeNodeId ? ' · SELECTED' : ''}`);
      }
    });
  }, [nodes, unavailableNodeIds, options.nodeLabels, computeNodeId]);

  useEffect(() => {
    const viewer = viewerRef.current; if (!viewer) return;
    for (const entity of [...viewer.entities.values]) if (entity.id.startsWith('link:') || entity.id.startsWith('route:') || entity.id.startsWith('failed:') || entity.id.startsWith('recovered:')) viewer.entities.remove(entity);
    const positions = new Map(nodes.map((node) => [node.nodeId, Cartesian3.fromDegrees(node.longitudeDeg, node.latitudeDeg, node.altitudeM)]));
    const addLine = (id: string, edge: Link, width: number, material: Color | PolylineDashMaterialProperty) => {
      const from = positions.get(edge[0]); const to = positions.get(edge[1]); if (from && to) viewer.entities.add({ id, polyline: { positions: [from, to], width, material } });
    };
    if (options.allLinks) normalLinks.forEach((edge) => addLine(`link:${linkKey(edge)}`, edge, 1.25, Color.fromCssColorString('#3fdde599')));
    if (options.selectedRoute) route.slice(0, -1).forEach((from, index) => addLine(`route:${from}-${route[index + 1]}`, [from, route[index + 1]], 5, Color.fromCssColorString('#fff36a')));
    if (options.failedLinks) failedLinks.forEach((edge) => addLine(`failed:${edge[0]}-${edge[1]}`, edge, 4, new PolylineDashMaterialProperty({ color: Color.RED, dashLength: 12 })));
    recoveredLinks.forEach((edge) => addLine(`recovered:${edge[0]}-${edge[1]}`, edge, 3, Color.fromCssColorString('#3dd9a7')));
  }, [nodes, normalLinks, route, failedLinks, recoveredLinks, options.allLinks, options.selectedRoute, options.failedLinks]);

  useEffect(() => { if (selected && viewerRef.current) viewerRef.current.camera.flyTo({ destination: Cartesian3.fromDegrees(selected.longitudeDeg, selected.latitudeDeg, selected.nodeType === 'SATELLITE' ? Math.max(selected.altitudeM * 2.8, 1_500_000) : 900_000), duration: 1.2 }); }, [selected]);
  return <div className="globe-wrap"><div className="globe-overlay"><span><i className="legend satellite" /> 위성</span><span><i className="legend compute" /> 연산 위성</span><span><i className="legend station" /> 지상국</span><span><i className="legend failed" /> 장애</span><span><i className="legend recovered" /> 복구</span></div><div className="cesium-container" ref={containerRef} /></div>;
}
