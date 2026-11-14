import { useEffect, useMemo, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { connectivity, measurement, temperature, type Clinic } from './api';

function clinicPosition(clinic: Clinic): [number, number] | null {
  const { lat, lon } = clinic;
  return typeof lat === 'number' && Number.isFinite(lat) && Math.abs(lat) <= 90
    && typeof lon === 'number' && Number.isFinite(lon) && Math.abs(lon) <= 180 ? [lat, lon] : null;
}
export default function ClinicMap({ clinics, selected, onSelect }: { clinics: Clinic[]; selected: string; onSelect: (id: string) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const select = useRef(onSelect);
  const fitted = useRef('');
  const positions = useMemo(() => clinics.flatMap(clinic => { const position = clinicPosition(clinic); return position ? [position] : []; }), [clinics]);
  const boundsKey = JSON.stringify(positions.map(position => position.join(',')).sort());
  useEffect(() => { select.current = onSelect; }, [onSelect]);
  useEffect(() => {
    if (!container.current) return;
    const instance = L.map(container.current, { scrollWheelZoom: false });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(instance);
    layer.current = L.layerGroup().addTo(instance);
    map.current = instance;
    const resize = new ResizeObserver(() => instance.invalidateSize());
    resize.observe(container.current);
    return () => { resize.disconnect(); instance.remove(); map.current = null; fitted.current = ''; };
  }, []);
  useEffect(() => {
    if (positions.length && fitted.current !== boundsKey) {
      const focus = clinics.find(clinic => clinic.monitored !== false && clinic.alarm_state !== 'NORMAL' && clinic.alarm_state !== 'OFFLINE' && clinicPosition(clinic))
        || clinics.find(clinic => clinic.monitored === true && clinicPosition(clinic));
      const center = focus ? clinicPosition(focus)! : positions[0];
      const radians = Math.PI / 180;
      const distance = ([lat, lon]: [number, number]) => {
        const latitude = Math.sin((lat - center[0]) * radians / 2);
        const longitude = Math.sin((lon - center[1]) * radians / 2);
        return latitude * latitude + Math.cos(center[0] * radians) * Math.cos(lat * radians) * longitude * longitude;
      };
      const nearby = [...positions].sort((a, b) => distance(a) - distance(b)).slice(0, 5);
      map.current?.fitBounds(nearby, { padding: [40, 40], maxZoom: 13 });
      fitted.current = boundsKey;
    }
    layer.current?.clearLayers();
    clinics.forEach(clinic => {
      const position = clinicPosition(clinic);
      if (!position || !layer.current) return;
      const monitored = clinic.monitored !== false;
      const alarm = monitored && clinic.alarm_state !== 'NORMAL' && clinic.alarm_state !== 'OFFLINE';
      const label = monitored ? `${clinic.name}: ${temperature(clinic.last_temp_c)} Celsius, ${measurement(clinic)}, ${connectivity(clinic)}` : `${clinic.name}: Not monitored / estimated capacity`;
      const icon = L.divIcon({ className: '', html: `<span class="map-pin ${!monitored ? 'destination' : ''} ${alarm ? 'alarm' : ''} ${selected === clinic.id ? 'selected' : ''}"><span></span></span>`, iconSize: [28, 28], iconAnchor: [14, 14] });
      const marker = L.marker(position, { icon, title: label, alt: label, keyboard: true }).addTo(layer.current);
      const text = document.createElement('span'); text.textContent = clinic.name;
      marker.bindTooltip(text, { direction: 'top', offset: [0, -12] });
      marker.on('click', () => select.current(clinic.id));
    });
  }, [clinics, selected, boundsKey, positions]);
  return <><div ref={container} className="clinic-map" style={!positions.length ? { visibility: 'hidden' } : undefined} role="region" aria-label="Finland clinic map. Use the clinic list as a keyboard-accessible alternative." />{positions.length < clinics.length || !positions.length ? <p className="map-unavailable" role="status">{positions.length ? `${clinics.length - positions.length} sites have no valid coordinates and are not mapped.` : 'No valid site coordinates available from the service. No fallback locations are shown.'} Use the clinic list to select any site.</p> : null}</>;
}
