# Interaktions- und Animationskonzept für 3D-Agenten im Büro

Dieses Konzept beschreibt einfache, gut skalierbare Animationen und Interaktionen für eine 3D-Büroansicht mit Hauptagent, Sub-Agenten und optionalen Agentengruppen. Ziel ist, Zustände sofort erkennbar zu machen, ohne die Szene visuell zu überladen oder bei vielen Agenten die Performance zu gefährden.

## Ziele

- Jeder Agent zeigt seinen Zustand über kleine Bewegungen, Farbe, Blickrichtung und Hervorhebung.
- Animationen bleiben subtil, lesbar und kombinierbar.
- Der Hauptagent ist visuell als Koordinationszentrum erkennbar.
- Sub-Agenten können einzeln, gruppiert oder als Team wahrgenommen werden.
- Die technische Umsetzung funktioniert sowohl in Three.js als auch in React Three Fiber.
- Viele Agenten sollen mit wenig CPU/GPU-Last dargestellt werden können.

## Agentenmodell

Jeder Agent besitzt eine kleine Zustandsbeschreibung:

```ts
type AgentState = 'idle' | 'working' | 'thinking' | 'error' | 'done'

type AgentViewModel = {
  id: string
  role: 'main' | 'sub'
  state: AgentState
  position: [number, number, number]
  targetAgentId?: string
  selected?: boolean
  groupId?: string
  activityLevel?: number // 0..1, beeinflusst Animationsintensität
}
```

Empfohlene visuelle Bausteine pro Agent:

- Körper oder Avatar: einfache Figur, Kugel-/Capsule-Agent oder stilisierter Büroarbeiter.
- Schreibtisch/Terminal: kleine Arbeitsfläche, Bildschirm oder Tastatur.
- Statusring am Boden: Farbe und Puls zeigen Zustand.
- Blickrichtung: Kopf, Augen, Bildschirm oder kleiner Pfeil/Marker.
- Auswahl-Halo: sichtbare Hervorhebung bei Hover/Click.

## Zustände und Animationen

| Zustand | Bewegung | Farbe/Signal | Bedeutung |
|---|---|---|---|
| `idle` | sehr leichtes Wippen/Atmen, langsame Mikro-Rotation | neutral/blau-grau | wartet auf Aufgabe |
| `working` | Tippen am Schreibtisch, schnelleres Bildschirmflackern, leichtes Vorlehnen | blau oder cyan | führt Tool-/Arbeitsprozess aus |
| `thinking` | langsames Kopfneigen, Blick nach oben oder zum Hauptagenten, pulsierender Ring | violett/gelb | plant, analysiert oder wartet auf Modellantwort |
| `error` | kurzes Schütteln, roter Blinkimpuls, eingefrorene Arbeitsbewegung | rot/orange | Fehler, Blockade oder fehlgeschlagener Schritt |
| `done` | kurzes Aufrichten, grüner Ring, kleiner Bounce, danach ruhiges Idle | grün | Teilaufgabe abgeschlossen |

### Idle

- Agent wippt sanft auf der Y-Achse: `sin(time * 1.2 + phase) * 0.025`.
- Kopf oder Körper rotiert minimal: `sin(time * 0.8 + phase) * 0.03`.
- Statusring bleibt konstant oder pulsiert sehr langsam.

### Working

- Hände/Tastatur-Proxy bewegen sich abwechselnd nach unten/oben.
- Oberkörper lehnt sich leicht Richtung Schreibtisch.
- Bildschirmhelligkeit oder Emissive-Intensität flackert sehr subtil.
- Aktivere Sub-Agenten können höhere Frequenz haben, aber keine großen Bewegungen.

### Thinking

- Agent blickt zum Hauptagenten, zu einer Wandtafel oder leicht nach oben.
- Statusring pulsiert langsam: größer/kleiner, nicht blinkend.
- Optional: kleine Gedankenpunkte über dem Kopf, die nacheinander ein-/ausblenden.
- Bei Sub-Agenten in Abstimmung: Blickrichtung zum Hauptagenten oder Gruppenzentrum.

### Error

- Kurze Shake-Animation auf X/Z: 3 bis 5 schnelle Ausschläge.
- Statusring blinkt rot für ca. 1 Sekunde, danach roter Dauerzustand.
- Kopf/Display kann leicht nach unten zeigen.
- Wichtig: Fehleranimation zeitlich begrenzen, damit viele Fehler nicht hektisch wirken.

### Done

- Einmaliger kleiner Bounce oder Aufrichten beim Zustandswechsel.
- Grüner Statusring pulsiert 1 bis 2 Mal.
- Danach Rückkehr in ruhiges `idle` oder weiterhin `done` mit sehr statischem Verhalten.

## Interaktionen

### Hover

- Agent hebt sich leicht an oder erhält einen dünnen Outline-/Halo-Ring.
- Cursor-Hover zeigt Kurzinfo: Name, Rolle, Status, aktuelle Aufgabe.
- Animationen werden nicht komplett geändert, nur Hervorhebung addiert.

### Auswahl

- Ausgewählter Agent bekommt:
  - helleren Bodenring,
  - dezente Outline,
  - leichte Skalierung, z. B. `scale = 1.06`,
  - optional eine Verbindungslinie zum Hauptagenten oder zu abhängigen Sub-Agenten.
- Kamera kann optional sanft zum Agenten schwenken, aber nicht automatisch bei jeder Auswahl springen.

### Blickrichtung zum Hauptagenten

Sub-Agenten sollen bei Koordination oder `thinking` sichtbar Bezug auf den Hauptagenten nehmen:

- Kopf oder Oberkörper rotiert horizontal Richtung Hauptagent.
- Nur Yaw-Rotation verwenden, damit Agenten nicht unnatürlich kippen.
- Rotation wird weich interpoliert (`lerp`/`slerp`), nicht hart gesetzt.

### Gruppenbildung

Agenten mit gleichem `groupId` bilden visuelle Cluster:

- Kreis, Halbkreis oder Insel um ein gemeinsames Gruppenzentrum.
- Dünne farbige Bodenfläche oder gemeinsamer Teppich unter der Gruppe.
- Verbindungslinien nur sparsam nutzen, z. B. bei aktiven Abhängigkeiten.
- Gruppenstatus kann als aggregierter Ring oder kleines Schild am Gruppenzentrum erscheinen.

Mögliche Layout-Regel:

```ts
const angle = (index / groupSize) * Math.PI * 2
const radius = 1.2 + groupSize * 0.08
agent.position.x = groupCenter.x + Math.cos(angle) * radius
agent.position.z = groupCenter.z + Math.sin(angle) * radius
```

### Auswahl einer Gruppe

- Alle Gruppenmitglieder erhalten einen schwachen Halo.
- Der primäre aktive Agent der Gruppe wird stärker hervorgehoben.
- Kamera fokussiert auf Gruppenzentrum statt auf einen einzelnen Agenten.

## Technische Umsetzung in React Three Fiber

### Grundstruktur

```tsx
function Agent({ agent, mainPosition }: { agent: AgentViewModel; mainPosition: THREE.Vector3 }) {
  const root = useRef<THREE.Group>(null)
  const body = useRef<THREE.Mesh>(null)
  const ring = useRef<THREE.Mesh>(null)
  const phase = useMemo(() => Math.random() * Math.PI * 2, [])

  useFrame((_, delta) => {
    const t = performance.now() * 0.001
    if (!root.current) return

    applyStateMotion({ root: root.current, body: body.current, ring: ring.current, agent, mainPosition, t, delta, phase })
  })

  return (
    <group ref={root} position={agent.position}>
      <mesh ref={body}>{/* avatar geometry */}</mesh>
      <mesh ref={ring} rotation-x={-Math.PI / 2}>{/* status ring */}</mesh>
    </group>
  )
}
```

### Einfache Transformationsupdates

```ts
function applyStateMotion(ctx: MotionContext) {
  const { root, body, ring, agent, mainPosition, t, delta, phase } = ctx

  const selectedScale = agent.selected ? 1.06 : 1.0
  root.scale.lerp(new THREE.Vector3(selectedScale, selectedScale, selectedScale), delta * 8)

  if (agent.state === 'idle') {
    root.position.y = Math.sin(t * 1.2 + phase) * 0.025
    root.rotation.y = Math.sin(t * 0.8 + phase) * 0.03
  }

  if (agent.state === 'working') {
    root.position.y = Math.sin(t * 6.0 + phase) * 0.01
    if (body) body.rotation.x = -0.08 + Math.sin(t * 8.0 + phase) * 0.025
  }

  if (agent.state === 'thinking') {
    lookAtYaw(root, mainPosition, delta)
    if (ring) {
      const pulse = 1 + Math.sin(t * 2.2 + phase) * 0.08
      ring.scale.setScalar(pulse)
    }
  }

  if (agent.state === 'error') {
    root.position.x += Math.sin(t * 24.0 + phase) * 0.015
  }

  if (agent.state === 'done') {
    if (ring) ring.scale.setScalar(1 + Math.max(0, Math.sin(t * 4.0 + phase)) * 0.05)
  }
}
```

Wichtig: Wenn `root.position.y` animiert wird, sollte die Basisposition separat gespeichert werden. Sonst überschreibt die Animation absolute Layoutpositionen. In der Praxis nutzt man dafür `basePosition` und setzt `root.position.y = baseY + offset`.

### Blickrichtung weich interpolieren

```ts
function lookAtYaw(object: THREE.Object3D, target: THREE.Vector3, delta: number) {
  const dx = target.x - object.position.x
  const dz = target.z - object.position.z
  const targetYaw = Math.atan2(dx, dz)

  const current = object.rotation.y
  const next = THREE.MathUtils.lerp(current, targetYaw, Math.min(1, delta * 4))
  object.rotation.y = next
}
```

Bei komplexeren Avataren sollte nur Kopf oder Oberkörper rotieren. Bei einfachen Agenten reicht die gesamte Gruppe.

## Tweening für Zustandswechsel

Für einmalige Übergänge wie `done`-Bounce, `error`-Shake oder Auswahl-Hervorhebung ist Tweening besser als permanente Sinuslogik.

Geeignete Bibliotheken:

- `@react-spring/three` für deklarative Federanimationen.
- `gsap` für Timeline-basierte Effekte.
- `maath/easing` für kleine, performante Interpolationen im `useFrame`.

Beispiel mit `@react-spring/three`:

```tsx
const { scale, emissiveIntensity } = useSpring({
  scale: agent.selected ? 1.06 : 1,
  emissiveIntensity: agent.state === 'error' ? 1.4 : 0.2,
  config: { tension: 220, friction: 18 },
})

return (
  <animated.group scale={scale}>
    <animated.meshStandardMaterial emissiveIntensity={emissiveIntensity} />
  </animated.group>
)
```

Für viele Agenten sollte man Tweens nur bei Zustandswechseln starten, nicht pro Frame neue Tween-Objekte erzeugen.

## Umsetzung in purem Three.js

Bei Three.js ohne React kann dieselbe Logik in einer zentralen Animationsschleife laufen:

```ts
const clock = new THREE.Clock()

function animate() {
  requestAnimationFrame(animate)
  const t = clock.getElapsedTime()
  const delta = clock.getDelta()

  for (const agent of agents) {
    updateAgentAnimation(agent, t, delta)
  }

  renderer.render(scene, camera)
}
```

Dabei enthält jeder Agent Referenzen auf `group`, `body`, `ring`, `basePosition`, `phase`, `state` und optionale Tween-Daten.

## Statusfarben und Materialstrategie

Empfohlene Farben:

```ts
const STATE_COLOR = {
  idle: '#7a8ca3',
  working: '#2fb7ff',
  thinking: '#b36bff',
  error: '#ff4d4d',
  done: '#4dff88',
}
```

Performance-Hinweise:

- Materialien pro Zustand wiederverwenden, nicht pro Agent neu erzeugen.
- Bei individuellen Farben Instancing mit Attributen oder Material-Uniforms verwenden.
- Emissive-Effekte sparsam einsetzen; Bloom nur für ausgewählte oder aktive Agenten.

## Performance bei vielen Agenten

### Empfehlungen

1. **Instancing für einfache Agenten**  
   Körper, Köpfe, Tische und Statusringe mit `InstancedMesh` rendern. Pro Agent werden Matrix und Farbe aktualisiert.

2. **Animation Level of Detail**  
   - nahe/ausgewählte Agenten: volle Animation inklusive Tippen und Blickrichtung,
   - mittlere Distanz: nur Wippen und Statusring,
   - weit entfernte Agenten: statisch oder sehr selten aktualisiert.

3. **Update-Budgeting**  
   Nicht jeder Agent muss in jedem Frame vollständig aktualisiert werden. Für weit entfernte Agenten reicht z. B. jedes zweite bis fünfte Frame.

4. **Keine React-State-Updates pro Frame**  
   Animationswerte in Refs, Instanced-Matrizen oder externen Stores halten. `setState` im `useFrame` vermeiden.

5. **Phasenoffsets nutzen**  
   Zufällige `phase`-Werte verhindern synchrones Wippen und machen die Szene lebendiger, ohne mehr Logik zu brauchen.

6. **Geometrie einfach halten**  
   Agenten sollten aus wenigen Low-Poly-Geometrien bestehen. Detaillierte Avatare nur für Hauptagent oder ausgewählte Agenten.

7. **Frustum Culling und Sichtbarkeit**  
   Agenten außerhalb der Kamera nicht animieren oder nur aggregiert aktualisieren.

8. **Ereignisbasierte Spezialanimationen**  
   `error`-Shake und `done`-Bounce nur beim Zustandswechsel abspielen, nicht dauerhaft teuer simulieren.

### Instancing-Skizze

```tsx
function InstancedAgents({ agents }: { agents: AgentViewModel[] }) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const dummy = useMemo(() => new THREE.Object3D(), [])

  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    if (!mesh.current) return

    agents.forEach((agent, i) => {
      const phase = hashPhase(agent.id)
      const yOffset = agent.state === 'idle' ? Math.sin(t * 1.2 + phase) * 0.025 : 0
      dummy.position.set(agent.position[0], agent.position[1] + yOffset, agent.position[2])
      dummy.scale.setScalar(agent.selected ? 1.06 : 1)
      dummy.updateMatrix()
      mesh.current!.setMatrixAt(i, dummy.matrix)
    })

    mesh.current.instanceMatrix.needsUpdate = true
  })

  return <instancedMesh ref={mesh} args={[undefined, undefined, agents.length]} />
}
```

Für Statusfarben kann zusätzlich `setColorAt` verwendet werden. Häufige Farbwechsel sollten gebündelt werden.

## Animationspriorität

Wenn mehrere Signale gleichzeitig aktiv sind, gilt folgende Priorität:

1. Auswahl/Hover als additive Hervorhebung.
2. Fehler als wichtigste Zustandsanimation.
3. Done-Impuls beim Übergang.
4. Working/Thinking als laufender Zustand.
5. Idle als Fallback.

Beispiel: Ein ausgewählter Agent im Fehlerzustand bleibt rot und schüttelt kurz, erhält aber zusätzlich den Auswahl-Halo.

## Empfohlene erste Implementierungsstufe

1. Statusring mit Zustandfarbe.
2. Idle-Wippen für alle Agenten.
3. Working-Tippen am Schreibtisch.
4. Thinking-Blickrichtung zum Hauptagenten plus Pulsring.
5. Error-Shake und Done-Bounce als Tween beim Zustandswechsel.
6. Hover- und Auswahl-Halo.
7. Gruppenlayout und Gruppenhervorhebung.
8. Instancing/LOD, sobald mehr als ca. 50 Agenten sichtbar sind.

## Akzeptanzkriterien

- Alle fünf Zustände sind in Bewegung und Farbe unterscheidbar.
- Sub-Agenten können sichtbar zum Hauptagenten oder Gruppenzentrum blicken.
- Auswahl und Hover sind klar erkennbar, ohne den Status zu verdecken.
- Gruppenbildung ist durch Layout und dezente gemeinsame Hervorhebung verständlich.
- Die Animationen laufen ohne React-Re-Render pro Frame.
- Bei vielen Agenten existiert ein Pfad zu Instancing, LOD und reduzierten Updatefrequenzen.
