import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { connectivity, measurement, temperature, type Clinic } from './api';

// City centres are geographic labels, not the addresses of real medical sites.
const cities: Record<string, [number, number]> = { helsinki: [60.1699, 24.9384], espoo: [60.2055, 24.6559], tampere: [61.4978, 23.761], vantaa: [60.2934, 25.0378], oulu: [65.0121, 25.4651] };
export default function ClinicMap({ clinics, selected, onSelect }: { clinics: Clinic[]; selected: string; onSelect: (id: string) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const select = useRef(onSelect);
  useEffect(() => { select.current = onSelect; }, [onSelect]);
  useEffect(() => {
    if (!container.current) return;
    const instance = L.map(container.current, { scrollWheelZoom: false }).fitBounds(Object.values(cities), { padding: [40, 40] });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(instance);
    layer.current = L.layerGroup().addTo(instance);
    map.current = instance;
    const resize = new ResizeObserver(() => instance.invalidateSize());
    resize.observe(container.current);
    return () => { resize.disconnect(); instance.remove(); map.current = null; };
  }, []);
  useEffect(() => {
    layer.current?.clearLayers();
    clinics.forEach(clinic => {
      const position = cities[clinic.clinic_id];
      if (!position || !layer.current) return;
      const alarm = clinic.alarm_state !== 'NORMAL' && clinic.alarm_state !== 'OFFLINE';
      const label = `${clinic.city}: ${temperature(clinic.last_temp_c)} Celsius, ${measurement(clinic)}, ${connectivity(clinic)}`;
      const icon = L.divIcon({ className: '', html: `<span class="map-pin ${alarm ? 'alarm' : ''} ${selected === clinic.id ? 'selected' : ''}"><span></span></span>`, iconSize: [28, 28], iconAnchor: [14, 14] });
      const marker = L.marker(position, { icon, title: label, alt: label, keyboard: true }).addTo(layer.current);
      const text = document.createElement('span'); text.textContent = clinic.city;
      marker.bindTooltip(text, { direction: 'top', offset: [0, -12] });
      marker.on('click', () => select.current(clinic.id));
    });
  }, [clinics, selected]);
  return <div ref={container} className="clinic-map" role="region" aria-label="Finland clinic map. Use the clinic list as a keyboard-accessible alternative." />;
}
