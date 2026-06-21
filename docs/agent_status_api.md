# Datenmodell und API-Anbindung für Agentenstatus

Diese Spezifikation definiert ein stabiles Datenmodell und eine API-Anbindung, damit die WebUI Haupt-Agenten und Sub-Agents hierarchisch gruppiert und in einer 3D-Szene darstellen kann. Sie ist kompatibel mit der bestehenden WebUI-Idee aus `zuse/webui.py`, in der Agenten bereits über `crew_update`-Events gerendert werden.

## Ziele

- Einheitliches JSON-Modell für Haupt-Agenten, Sub-Agents und Crew-Rollen.
- Hierarchische Gruppierung über `parentId` und optional vorberechnete `children`.
- Klare Statuswerte für Backend, API und visuelle Darstellung.
- Positionsdaten entweder deterministisch im Frontend berechnen oder vom Backend persistiert liefern.
- Live-Updates mit Event-Stream, WebSocket oder Polling fallbackfähig bereitstellen.

## Agent JSON-Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://zuse.local/schemas/agent-status.schema.json",
  "title": "Zuse Agent Status",
  "type": "object",
  "additionalProperties": false,
  "required": ["id", "name", "type", "status", "progress", "lastUpdate"],
  "properties": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 128,
      "pattern": "^[A-Za-z0-9._:-]+$",
      "description": "Stabile technische ID, z. B. zuse, crew:researcher:1."
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 120,
      "description": "Anzeigename in der WebUI."
    },
    "type": {
      "type": "string",
      "enum": ["root", "agent", "subagent", "crew", "tool", "supervisor"],
      "description": "Rolle im Agentenbaum."
    },
    "parentId": {
      "type": ["string", "null"],
      "maxLength": 128,
      "description": "ID des Elternknotens. null oder fehlend für Root-Agenten."
    },
    "status": {
      "type": "string",
      "enum": ["initializing", "queued", "running", "waiting", "blocked", "done", "failed", "cancelled", "idle"],
      "description": "Maschinenlesbarer Zustand."
    },
    "task": {
      "type": ["string", "null"],
      "maxLength": 500,
      "description": "Aktuelle Aufgabe oder Kurzbeschreibung."
    },
    "progress": {
      "type": "number",
      "minimum": 0,
      "maximum": 100,
      "description": "Fortschritt in Prozent. Unbekannt: 0 bei queued/initializing oder heuristisch setzen."
    },
    "lastUpdate": {
      "type": "string",
      "format": "date-time",
      "description": "Zeitpunkt der letzten Zustandsänderung als ISO-8601 UTC Timestamp."
    },
    "metadata": {
      "type": "object",
      "additionalProperties": true,
      "description": "Erweiterbare Zusatzdaten ohne harte UI-Abhängigkeit.",
      "properties": {
        "role": { "type": "string" },
        "model": { "type": "string" },
        "provider": { "type": "string" },
        "jobId": { "type": "string" },
        "step": { "type": "integer", "minimum": 0 },
        "maxSteps": { "type": "integer", "minimum": 0 },
        "todosDone": { "type": "integer", "minimum": 0 },
        "todosTotal": { "type": "integer", "minimum": 0 },
        "error": { "type": "string" },
        "tags": { "type": "array", "items": { "type": "string" } }
      }
    },
    "position": {
      "type": "object",
      "additionalProperties": false,
      "description": "Optionale persistierte oder backendberechnete 3D-Position.",
      "required": ["x", "y", "z"],
      "properties": {
        "x": { "type": "number" },
        "y": { "type": "number" },
        "z": { "type": "number" },
        "rotationY": { "type": "number", "default": 0 },
        "layout": { "type": "string", "enum": ["manual", "hierarchical", "radial", "grid"], "default": "hierarchical" }
      }
    }
  }
}
```

### Feldkonventionen

- `id` muss über die Lebensdauer eines Jobs stabil bleiben. Für wiederverwendbare Rollen empfiehlt sich `crew:<jobId>:<role>` oder `agent:<uuid>`.
- `name` ist UI-freundlich; technische Rollen gehören in `metadata.role`.
- `type=root` ist der Haupt-Agent. `type=crew` kann als Gruppenknoten verwendet werden, wenn mehrere Sub-Agents als Team visualisiert werden sollen.
- `parentId` bildet die Hierarchie. Ein Agent darf nicht sein eigener Parent sein; Zyklen sind serverseitig zu verhindern.
- `progress` ist numerisch und immer vorhanden. Wenn nur Schritte bekannt sind: `step / maxSteps * 100`. Wenn Todos bekannt sind: `todosDone / todosTotal * 100`. Bei `done` immer `100`, bei `failed` letzter bekannter Wert.
- `metadata` darf erweitert werden, muss aber nicht für kritische UI-Logik erforderlich sein.

## API-Endpunkte

### `GET /api/agents`

Liefert den aktuellen Snapshot aller Agenten flach und optional als Baum.

Query-Parameter:

- `tree=true|false` — optional, default `false`. Bei `true` wird zusätzlich `tree` geliefert.
- `includePosition=true|false` — optional, default `true`.

Response:

```json
{
  "version": 1,
  "timestamp": "2026-06-21T12:00:00Z",
  "layout": {
    "mode": "hierarchical",
    "coordinateSystem": "office-percent-v1",
    "units": "percent"
  },
  "agents": [
    {
      "id": "zuse",
      "name": "Zuse",
      "type": "root",
      "parentId": null,
      "status": "running",
      "task": "Koordiniert Implementierung",
      "progress": 42,
      "lastUpdate": "2026-06-21T11:59:58Z",
      "metadata": {
        "role": "Lead",
        "provider": "anthropic",
        "model": "claude-sonnet-4"
      },
      "position": { "x": 50, "y": 18, "z": 0, "rotationY": 0, "layout": "hierarchical" }
    },
    {
      "id": "crew:abc123:researcher",
      "name": "Researcher",
      "type": "subagent",
      "parentId": "zuse",
      "status": "done",
      "task": "API-Optionen prüfen",
      "progress": 100,
      "lastUpdate": "2026-06-21T11:59:40Z",
      "metadata": {
        "role": "Researcher",
        "jobId": "abc123",
        "todosDone": 3,
        "todosTotal": 3
      },
      "position": { "x": 28, "y": 54, "z": 0, "rotationY": -15, "layout": "hierarchical" }
    },
    {
      "id": "crew:abc123:tester",
      "name": "Tester",
      "type": "subagent",
      "parentId": "zuse",
      "status": "blocked",
      "task": "Wartet auf lauffähige Änderung",
      "progress": 20,
      "lastUpdate": "2026-06-21T11:59:55Z",
      "metadata": {
        "role": "Tester",
        "jobId": "abc123"
      },
      "position": { "x": 72, "y": 54, "z": 0, "rotationY": 15, "layout": "hierarchical" }
    }
  ]
}
```

### `GET /api/agents/{id}`

Liefert Detaildaten eines Agenten inklusive Child-IDs und letzter Ereignisse.

```json
{
  "agent": {
    "id": "crew:abc123:tester",
    "name": "Tester",
    "type": "subagent",
    "parentId": "zuse",
    "status": "blocked",
    "task": "Wartet auf lauffähige Änderung",
    "progress": 20,
    "lastUpdate": "2026-06-21T11:59:55Z",
    "metadata": { "role": "Tester", "jobId": "abc123" }
  },
  "children": [],
  "events": [
    { "id": 184, "type": "status", "timestamp": "2026-06-21T11:59:55Z", "status": "blocked" }
  ]
}
```

### `PATCH /api/agents/{id}/position`

Optionaler Endpunkt, wenn die WebUI manuelle Drag-and-drop-Positionen speichern darf.

Request:

```json
{
  "position": { "x": 44, "y": 63, "z": 0, "rotationY": 10, "layout": "manual" }
}
```

Response:

```json
{
  "ok": true,
  "agentId": "crew:abc123:tester",
  "position": { "x": 44, "y": 63, "z": 0, "rotationY": 10, "layout": "manual" }
}
```

## Hierarchische Gruppierung

Die kanonische API-Repräsentation ist eine flache Liste mit `parentId`. Das vermeidet Duplikate, macht Diffs einfacher und erlaubt inkrementelle Updates. Die WebUI kann daraus einen Baum bauen:

```js
function buildAgentTree(agents) {
  const byId = new Map(agents.map(a => [a.id, { ...a, children: [] }]));
  const roots = [];

  for (const node of byId.values()) {
    if (node.parentId && byId.has(node.parentId) && node.parentId !== node.id) {
      byId.get(node.parentId).children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}
```

Empfehlungen:

- Root-Agent: `parentId: null`.
- Direkte Sub-Agents: `parentId: "zuse"`.
- Crew-Gruppen: Entweder `type=crew` als Zwischenknoten (`zuse -> crew -> subagent`) oder direkte Sub-Agents mit `metadata.jobId` gruppieren.
- Fehlende Parents werden als Root-Knoten gerendert und im Backend als Warnung geloggt.
- Backend validiert: eindeutige IDs, keine Zyklen, maximal sinnvolle Tiefe, z. B. 8 Ebenen.

## Positionsdaten: berechnen oder speichern

### Option A: Frontend berechnet Positionen deterministisch

Gut für Live-Daten, wenig Backend-Komplexität. Das Backend liefert keine oder nur teilweise `position`-Felder.

Heuristik für `office-percent-v1`:

```js
function assignHierarchicalPositions(agents) {
  const roots = buildAgentTree(agents);
  const positioned = [];

  function placeLevel(nodes, depth, minX = 12, maxX = 88) {
    const y = Math.min(82, 18 + depth * 28);
    nodes.forEach((node, index) => {
      const span = maxX - minX;
      const x = nodes.length === 1 ? (minX + maxX) / 2 : minX + (span * index) / (nodes.length - 1);
      node.position = node.position || {
        x,
        y,
        z: depth * 4,
        rotationY: x < 50 ? -12 : x > 50 ? 12 : 0,
        layout: "hierarchical"
      };
      positioned.push(node);

      if (node.children.length) {
        const childWidth = Math.max(18, span / Math.max(nodes.length, 1));
        placeLevel(node.children, depth + 1, Math.max(8, x - childWidth / 2), Math.min(92, x + childWidth / 2));
      }
    });
  }

  placeLevel(roots, 0);
  return positioned;
}
```

Vorteile: reproduzierbar, keine Speicherung nötig. Nachteil: Agenten können bei neuen Knoten springen; Animationen sollten Positionsänderungen weich interpolieren.

### Option B: Backend berechnet Positionen

Gut, wenn mehrere Clients dieselbe Szene sehen sollen oder Layout serverseitig kontrolliert werden muss. Das Backend berechnet `position` bei jedem Snapshot aus Hierarchie und Status. Persistenz ist optional.

Empfehlung:

- `position.layout=hierarchical` für automatisch berechnete Werte.
- `position.layout=manual` für gespeicherte UI-Positionen.
- Positionswerte in Prozent (`x`, `y`) plus Tiefenwert (`z`) halten, damit unterschiedliche Viewport-Größen funktionieren.

### Option C: Manuelle Positionen speichern

Gut für Dashboards. WebUI sendet `PATCH /api/agents/{id}/position`. Backend speichert pro Session, Workspace oder User.

Speicherschlüssel:

```text
<workspaceId>/<sessionId>/<agentId>
```

Fallback: Wenn keine manuelle Position existiert, wird automatisch berechnet.

## Live-Updates

### Empfehlung 1: Server-Sent Events als Standard

SSE passt gut zur aktuellen WebUI, weil der Server überwiegend Statusereignisse zum Browser streamt und der Browser Jobs separat per HTTP startet.

Endpoint: `GET /api/agents/events`

Events:

```text
event: agent_snapshot
id: 201
data: {"version":1,"timestamp":"2026-06-21T12:00:00Z","agents":[...]}

```

```text
event: agent_update
id: 202
data: {"agent":{"id":"crew:abc123:tester","status":"running","progress":35,"lastUpdate":"2026-06-21T12:00:04Z"}}

```

```text
event: agent_remove
id: 203
data: {"id":"crew:abc123:researcher","reason":"expired"}

```

Client-Verhalten:

- Beim Verbinden zuerst Snapshot laden (`GET /api/agents`) oder `agent_snapshot` erwarten.
- `Last-Event-ID` nutzen, um verpasste Events nach Reconnect fortzusetzen.
- Heartbeat alle 15–30 Sekunden (`: ping\n\n` oder leeres Event), damit Proxies die Verbindung offen halten.
- Wenn Reconnect-Lücke zu groß ist, vollständigen Snapshot neu laden.

### Empfehlung 2: WebSocket für bidirektionale Szenensteuerung

WebSocket lohnt sich, wenn die 3D-UI interaktiv wird, z. B. Drag-and-drop, Agenten anklicken, Fokus setzen, Debug-Kommandos senden.

Endpoint: `GET /api/agents/ws`

Nachrichten:

```json
{ "type": "subscribe", "topics": ["agents", "jobs"] }
```

```json
{ "type": "agent_update", "agent": { "id": "zuse", "status": "running", "progress": 45 } }
```

```json
{ "type": "position_update", "agentId": "zuse", "position": { "x": 50, "y": 18, "z": 0, "layout": "manual" } }
```

Vorteile: bidirektional, geringe Latenz. Nachteile: mehr Infrastruktur, Reconnect/Backpressure/Auth komplexer als SSE.

### Empfehlung 3: Polling als Fallback

Polling ist robust und einfach, sollte aber als Fallback genutzt werden.

- Endpoint: `GET /api/agents?since=<timestamp-or-event-id>`.
- Intervall: 2–5 Sekunden bei aktiven Jobs, 10–30 Sekunden im Idle-Zustand.
- Response kann entweder vollständigen Snapshot oder Delta liefern.

Delta-Beispiel:

```json
{
  "version": 1,
  "since": 200,
  "latestEventId": 203,
  "updates": [
    { "id": "zuse", "status": "running", "progress": 45, "lastUpdate": "2026-06-21T12:00:04Z" }
  ],
  "removed": []
}
```

## Mapping von Agentenstatus zu visuellen Eigenschaften

| Status | Farbe | Animation | Opazität | Icon/Signal | Priorität |
|---|---:|---|---:|---|---:|
| `initializing` | `#94a3b8` | langsames Pulsieren | 0.80 | Spinner | 2 |
| `queued` | `#64748b` | keine oder leichtes Warten | 0.75 | Uhr | 2 |
| `idle` | `#0f172a` | keine | 0.90 | Standby | 1 |
| `running` | `#2563eb` | Halo-Puls, leichte Laufbewegung | 1.00 | Play/Blitz | 4 |
| `waiting` | `#f59e0b` | langsames Atmen | 0.95 | Pause | 3 |
| `blocked` | `#d97706` | Warnpuls | 1.00 | Warnsymbol | 5 |
| `done` | `#16a34a` | kurzer Erfolgspuls, dann statisch | 1.00 | Haken | 1 |
| `failed` | `#dc2626` | roter Puls oder Shake | 1.00 | X/Fehler | 6 |
| `cancelled` | `#71717a` | keine | 0.65 | Stopp | 2 |

Beispiel-Mapping für die WebUI:

```js
const STATUS_STYLE = {
  initializing: { color: '#94a3b8', halo: true, animation: 'pulse-slow', label: 'Initialisiert' },
  queued:       { color: '#64748b', halo: false, animation: 'none', label: 'Wartet' },
  idle:         { color: '#0f172a', halo: false, animation: 'none', label: 'Bereit' },
  running:      { color: '#2563eb', halo: true, animation: 'pulse', label: 'Arbeitet' },
  waiting:      { color: '#f59e0b', halo: true, animation: 'breathe', label: 'Wartet auf Input' },
  blocked:      { color: '#d97706', halo: true, animation: 'warning', label: 'Blockiert' },
  done:         { color: '#16a34a', halo: false, animation: 'success', label: 'Fertig' },
  failed:       { color: '#dc2626', halo: true, animation: 'shake', label: 'Fehler' },
  cancelled:    { color: '#71717a', halo: false, animation: 'none', label: 'Abgebrochen' }
};

function visualForAgent(agent) {
  const style = STATUS_STYLE[agent.status] || STATUS_STYLE.idle;
  return {
    ...style,
    progress: Math.max(0, Math.min(100, Number(agent.progress || 0))),
    scale: agent.type === 'root' ? 1.15 : agent.type === 'crew' ? 1.05 : 1.0,
    nameplate: agent.name,
    tooltip: `${agent.name}: ${style.label} · ${agent.progress}%`
  };
}
```

CSS-Klassen können direkt aus `status` erzeugt werden, z. B. `.agent3d.running`, `.agent3d.failed`. Unbekannte Statuswerte müssen auf `idle` oder `queued` fallen, damit die UI nicht bricht.

## Backend-Mapping aus bestehender Crew-Telemetrie

Falls interne Events aktuell Felder wie `role`, `title`, `activity`, `step`, `max_steps`, `todos_done`, `todos_total` liefern, kann ein Adapter das neue Modell erzeugen:

```python
from datetime import datetime, timezone

DONE_STATUSES = {"done", "success", "completed"}
ERROR_STATUSES = {"error", "failed"}


def normalize_agent(raw: dict, parent_id: str = "zuse") -> dict:
    status = raw.get("status") or "queued"
    if status in DONE_STATUSES:
        status = "done"
    elif status in ERROR_STATUSES:
        status = "failed"

    todos_total = raw.get("todos_total") or raw.get("todosTotal") or 0
    todos_done = raw.get("todos_done") or raw.get("todosDone") or 0
    max_steps = raw.get("max_steps") or raw.get("maxSteps") or 0
    step = raw.get("step") or 0

    if status == "done":
        progress = 100
    elif todos_total:
        progress = round(todos_done / todos_total * 100)
    elif max_steps:
        progress = min(100, round(step / max_steps * 100))
    elif status == "running":
        progress = raw.get("progress", 45)
    else:
        progress = raw.get("progress", 0)

    return {
        "id": raw.get("id") or f"agent:{raw.get('role', 'unknown')}",
        "name": raw.get("name") or raw.get("title") or raw.get("role") or "Agent",
        "type": raw.get("type") or "subagent",
        "parentId": raw.get("parentId", parent_id),
        "status": status,
        "task": raw.get("task") or raw.get("activity"),
        "progress": max(0, min(100, progress)),
        "lastUpdate": raw.get("lastUpdate") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metadata": {
            "role": raw.get("role"),
            "step": step,
            "maxSteps": max_steps,
            "todosDone": todos_done,
            "todosTotal": todos_total,
            "jobId": raw.get("job_id") or raw.get("jobId"),
            "error": raw.get("error")
        }
    }
```

## Fehler- und Kompatibilitätsregeln

- API-Version über `version` im Response-Envelope erhöhen, wenn Felder inkompatibel geändert werden.
- Neue optionale Felder nur additiv einführen.
- `metadata` nie für Pflichtdarstellung voraussetzen.
- Datumswerte immer UTC ISO-8601 liefern.
- Für sehr alte oder abgeschlossene Agenten kann das Backend `agent_remove` senden oder Snapshots auf die letzten N Agenten begrenzen.
- Authentifizierung/CSRF an bestehende WebUI-Sicherheitsregeln koppeln, besonders bei `PATCH /position` und WebSocket-Kommandos.
