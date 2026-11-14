import { useEffect } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet'
import type { LatLngBoundsExpression } from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { AssessedClinic, Clinic, Site } from '../../api/board'

function FitBounds({ bounds }: { bounds: LatLngBoundsExpression }) {
  const map = useMap()
  useEffect(() => {
    map.fitBounds(bounds, { padding: [30, 30] })
  }, [map, bounds])
  return null
}

export default function ClinicsMap({ main, clinics, active }: {
  main: Site | null
  clinics: (Clinic | AssessedClinic)[]
  active: boolean
}) {
  const points: [number, number][] = clinics.map((c) => [c.lat, c.lon])
  if (main) points.push([main.lat, main.lon])
  if (points.length === 0) return null

  return (
    <MapContainer center={points[0]} zoom={11} className="h-96 w-full rounded-lg bg-slate-800">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <FitBounds bounds={points} />
      {clinics.map((c) => {
        const reachable = 'reachable' in c ? c.reachable : null
        const color = !active || reachable == null ? '#38bdf8' : reachable ? '#10b981' : '#64748b'
        return (
          <CircleMarker
            key={c.id}
            center={[c.lat, c.lon]}
            radius={9}
            pathOptions={{ color: '#0f172a', weight: 2, fillColor: color, fillOpacity: 0.95 }}
          >
            <Popup>
              <strong>{c.name}</strong>
              <br />
              {c.address}, {c.city}
              <br />
              {c.phone ?? '—'}
              <br />
              {c.drive_minutes} min drive{c.accepts_after_hours ? ' · 24/7' : ''}
            </Popup>
          </CircleMarker>
        )
      })}
      {main && (
        <CircleMarker
          center={[main.lat, main.lon]}
          radius={12}
          pathOptions={{ color: '#0f172a', weight: 3, fillColor: '#ef4444', fillOpacity: 1 }}
        >
          <Popup>
            <strong>{main.name}</strong>
            <br />
            {main.address}
            <br />
            Fridge location
          </Popup>
        </CircleMarker>
      )}
    </MapContainer>
  )
}
