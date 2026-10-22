/**
 * Gêmeo digital do pátio para a página inicial — Three.js puro, sem React.
 *
 * O que a cena conta é o que o produto faz: o caminhão entra pela portaria (a cancela
 * abre), para na balança (o indicador acende), estaciona numa vaga, encosta de ré numa
 * doca (a porta sobe) e sai pela portaria de saída. A câmera voa entre capítulos
 * conforme a rolagem — quem controla o progresso é o GSAP na página.
 *
 * Unidades em metros. X para a direita, Z para quem olha, Y para cima.
 */

import gsap from 'gsap'
import * as THREE from 'three'

export type HotspotId = 'gate' | 'scale' | 'yard' | 'cold' | 'docks' | 'tower'

export interface HotspotScreen {
  id: HotspotId
  x: number
  y: number
  visible: boolean
  active: boolean
}

export interface YardScene {
  /** 0..1 — posição do voo de câmera ao longo dos capítulos. */
  setProgress: (progress: number) => void
  /** Posição em tela dos pontos de interesse, para os rótulos HTML. */
  hotspots: () => HotspotScreen[]
  setActive: (id: HotspotId | null) => void
  dispose: () => void
}

interface Options {
  reducedMotion: boolean
  lowPower: boolean
}

const COLORS = {
  bg: 0x07131f,
  ground: 0x0c1c2c,
  apron: 0x122536,
  road: 0x0f2031,
  line: 0x2b4d6b,
  edge: 0x4cc9f0,
  brand: 0xf28c28,
  building: 0x1f3d5a,
  white: 0xe8eef4,
  cold: 0x38bdf8,
  ok: 0x34d399,
  warn: 0xfbbf24,
}

const ROAD_Z = 50
const DOOR_Z = -15
const DOCK_X = (i: number) => -78 + i * 13.5
const ZONES = [
  { id: 'A', x0: -62, cold: false },
  { id: 'B', x0: -8, cold: false },
  { id: 'C', x0: 46, cold: true },
]
const SLOT_W = 5.6
const SLOTS_PER_ZONE = 8
const SLOT_Z0 = 64
const SLOT_DEPTH = 19
const slotX = (zone: number, i: number) => ZONES[zone]!.x0 + SLOT_W / 2 + i * SLOT_W
const GATE_IN_X = -165
const SCALE_X = -122
const GATE_OUT_X = 158

/**
 * Voo de câmera. Um quadro por capítulo; entre eles, curva suave (Catmull-Rom) para a
 * posição e interpolação linear do alvo — sem trancos na rolagem.
 */
const SHOTS: { pos: [number, number, number]; target: [number, number, number] }[] = [
  { pos: [110, 120, 235], target: [-55, 0, 18] }, // abertura: cena à direita do título
  { pos: [-222, 26, 92], target: [-160, 3, 52] }, // portaria
  { pos: [-150, 20, 96], target: [-118, 1, 50] }, // balança
  { pos: [40, 55, 160], target: [18, 0, 72] }, // pátio e cadeia fria
  { pos: [80, 52, 95], target: [12, 6, -14] }, // docas
  { pos: [-40, 70, 85], target: [-130, 26, -30] }, // torre
  { pos: [40, 190, 250], target: [0, 0, -5] }, // gêmeo digital completo
]

const HOTSPOTS: Record<HotspotId, THREE.Vector3> = {
  gate: new THREE.Vector3(GATE_IN_X, 12, 64),
  scale: new THREE.Vector3(SCALE_X, 7, 50),
  yard: new THREE.Vector3(-8, 8, 74),
  cold: new THREE.Vector3(68, 8, 74),
  docks: new THREE.Vector3(10, 22, -15),
  tower: new THREE.Vector3(-150, 38, -32),
}

export function createYardScene(canvas: HTMLCanvasElement, options: Options): YardScene {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !options.lowPower, alpha: false })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, options.lowPower ? 1.25 : 1.75))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.2
  renderer.shadowMap.enabled = !options.lowPower
  renderer.shadowMap.type = THREE.PCFSoftShadowMap

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(COLORS.bg)
  scene.fog = new THREE.Fog(COLORS.bg, 260, 620)

  const camera = new THREE.PerspectiveCamera(38, 1, 1, 2000)
  const disposables: { dispose: () => void }[] = []
  const track = <T extends { dispose: () => void }>(item: T) => {
    disposables.push(item)
    return item
  }

  /* ---------------- luz ---------------- */
  scene.add(new THREE.HemisphereLight(0xa9d0ff, 0x0d1c2b, 1.35))
  const sun = new THREE.DirectionalLight(0xfff1dc, 1.6)
  sun.position.set(-120, 220, 140)
  sun.castShadow = !options.lowPower
  sun.shadow.mapSize.set(2048, 2048)
  Object.assign(sun.shadow.camera, { left: -260, right: 260, top: 200, bottom: -200, near: 10, far: 600 })
  scene.add(sun)
  const rim = new THREE.DirectionalLight(0x4cc9f0, 0.45)
  rim.position.set(200, 80, -200)
  scene.add(rim)

  /* ---------------- materiais ---------------- */
  const mat = {
    ground: track(new THREE.MeshStandardMaterial({ color: COLORS.ground, roughness: 0.95 })),
    apron: track(new THREE.MeshStandardMaterial({ color: COLORS.apron, roughness: 0.9 })),
    road: track(new THREE.MeshStandardMaterial({ color: COLORS.road, roughness: 0.85 })),
    building: track(
      new THREE.MeshStandardMaterial({ color: COLORS.building, roughness: 0.6, metalness: 0.2 }),
    ),
    glass: track(
      new THREE.MeshStandardMaterial({
        color: 0x16374f,
        emissive: 0x0b4f6c,
        emissiveIntensity: 0.6,
        roughness: 0.15,
        metalness: 0.6,
      }),
    ),
    edge: track(new THREE.LineBasicMaterial({ color: COLORS.edge, transparent: true, opacity: 0.55 })),
    slotLine: track(
      new THREE.LineBasicMaterial({ color: COLORS.white, transparent: true, opacity: 0.28 }),
    ),
    coldLine: track(new THREE.LineBasicMaterial({ color: COLORS.cold, transparent: true, opacity: 0.7 })),
    marking: track(new THREE.MeshBasicMaterial({ color: 0xc9d6e2, transparent: true, opacity: 0.5 })),
    brand: track(new THREE.MeshStandardMaterial({ color: COLORS.brand, roughness: 0.45 })),
    cab: track(new THREE.MeshStandardMaterial({ color: 0xf1f4f7, roughness: 0.4, metalness: 0.2 })),
    trailer: track(new THREE.MeshStandardMaterial({ color: 0xc3ccd6, roughness: 0.55 })),
    reefer: track(new THREE.MeshStandardMaterial({ color: 0xe6f3fb, roughness: 0.4 })),
    tire: track(new THREE.MeshStandardMaterial({ color: 0x0b0f14, roughness: 0.9 })),
    door: track(new THREE.MeshStandardMaterial({ color: 0x2a4661, roughness: 0.5, metalness: 0.3 })),
    coldStripe: track(
      new THREE.MeshStandardMaterial({ color: COLORS.cold, emissive: COLORS.cold, emissiveIntensity: 0.4 }),
    ),
    display: track(
      new THREE.MeshStandardMaterial({ color: 0x16374f, emissive: 0x0b4f6c, emissiveIntensity: 0.9 }),
    ),
  }

  let visible = true

  /* ---------------- terreno ---------------- */
  const addBox = (
    w: number,
    h: number,
    d: number,
    material: THREE.Material,
    x: number,
    y: number,
    z: number,
    parent: THREE.Object3D = scene,
  ) => {
    const mesh = new THREE.Mesh(track(new THREE.BoxGeometry(w, h, d)), material)
    mesh.position.set(x, y, z)
    mesh.castShadow = true
    mesh.receiveShadow = true
    parent.add(mesh)
    return mesh
  }
  const addEdges = (mesh: THREE.Mesh, material: THREE.LineBasicMaterial = mat.edge) => {
    const lines = new THREE.LineSegments(track(new THREE.EdgesGeometry(mesh.geometry)), material)
    mesh.add(lines)
    return lines
  }

  const ground = new THREE.Mesh(track(new THREE.PlaneGeometry(900, 700)), mat.ground)
  ground.rotation.x = -Math.PI / 2
  ground.receiveShadow = true
  scene.add(ground)

  const grid = new THREE.GridHelper(900, 90, COLORS.line, COLORS.line)
  ;(grid.material as THREE.Material).transparent = true
  ;(grid.material as THREE.Material).opacity = 0.22
  grid.position.y = 0.02
  scene.add(grid)
  track(grid.geometry)

  const flat = (w: number, d: number, material: THREE.Material, x: number, z: number, y = 0.05) => {
    const mesh = new THREE.Mesh(track(new THREE.PlaneGeometry(w, d)), material)
    mesh.rotation.x = -Math.PI / 2
    mesh.position.set(x, y, z)
    mesh.receiveShadow = true
    scene.add(mesh)
    return mesh
  }
  flat(520, 16, mat.road, 0, ROAD_Z) // via principal
  flat(215, 58, mat.apron, 10, 14) // pátio de manobra das docas
  for (let x = -250; x < 260; x += 14) flat(6, 0.5, mat.marking, x, ROAD_Z, 0.07) // faixa central

  /* ---------------- armazém e docas ---------------- */
  const warehouse = addBox(210, 17, 46, mat.building, 10, 8.5, -38)
  addEdges(warehouse)
  addBox(212, 1.2, 48, mat.building, 10, 17.6, -38) // platibanda
  const roof = addBox(206, 0.3, 44, track(new THREE.MeshStandardMaterial({ color: 0x2a4d6e, roughness: 0.7 })), 10, 18.3, -38)
  roof.castShadow = false
  for (let i = 0; i < 9; i++) {
    // claraboias: dão escala ao telhado visto de cima
    addBox(4, 0.4, 36, mat.glass, -78 + i * 22, 18.6, -38).castShadow = false
  }
  const doors: THREE.Mesh[] = []
  const doorLights: THREE.Mesh[] = []
  for (let i = 0; i < 14; i++) {
    const x = DOCK_X(i)
    addBox(5.2, 0.4, 3, mat.brand, x, 1.4, DOOR_Z + 1.3) // nivelador
    const door = addBox(4.6, 5.2, 0.4, mat.door, x, 3.8, DOOR_Z - 0.1)
    door.geometry.translate(0, -2.6, 0) // pivô no topo: a porta "sobe" encolhendo
    door.position.y = 6.4
    doors.push(door)
    const light = new THREE.Mesh(
      track(new THREE.SphereGeometry(0.45, 12, 12)),
      track(new THREE.MeshBasicMaterial({ color: COLORS.ok })),
    )
    light.position.set(x + 3, 7.2, DOOR_Z + 0.3)
    scene.add(light)
    doorLights.push(light)
    flat(0.35, 22, mat.marking, x - 6.7, DOOR_Z + 11, 0.08)
  }

  /* ---------------- portarias, balança, torre ---------------- */
  const gatehouse = addBox(9, 6, 8, mat.building, GATE_IN_X, 3, 64)
  addEdges(gatehouse)
  addBox(10, 0.6, 9, mat.brand, GATE_IN_X, 6.3, 64)
  const exitHouse = addBox(9, 6, 8, mat.building, GATE_OUT_X, 3, 36)
  addEdges(exitHouse)
  addBox(10, 0.6, 9, mat.brand, GATE_OUT_X, 6.3, 36)

  const barrier = (x: number, pivotZ: number, dir: 1 | -1) => {
    const pivot = new THREE.Group()
    pivot.position.set(x, 2.6, pivotZ)
    const arm = addBox(0.5, 0.5, 15, mat.brand, 0, 0, dir * -7.5, pivot)
    arm.castShadow = true
    addBox(1.2, 2.6, 1.2, mat.building, x, 1.3, pivotZ, scene)
    scene.add(pivot)
    return pivot
  }
  const gateArm = barrier(GATE_IN_X + 4, 58, 1)
  const exitArm = barrier(GATE_OUT_X - 4, 42, -1)

  const scalePlatform = addBox(22, 0.35, 11, mat.door, SCALE_X, 0.2, ROAD_Z)
  const scaleFrame = addEdges(
    scalePlatform,
    track(new THREE.LineBasicMaterial({ color: COLORS.brand, transparent: true, opacity: 0.9 })),
  )
  addBox(3.2, 2, 0.4, mat.display, SCALE_X, 5.5, ROAD_Z + 9)
  addBox(0.4, 4.5, 0.4, mat.building, SCALE_X, 2.25, ROAD_Z + 9)

  const tower = addBox(9, 30, 9, mat.building, -150, 15, -32)
  addEdges(tower)
  const cabin = addBox(14, 6, 14, mat.glass, -150, 33, -32)
  addEdges(cabin)
  addBox(15, 0.8, 15, mat.brand, -150, 36.4, -32)

  /* ---------------- zonas e vagas ---------------- */
  ZONES.forEach((zone) => {
    const width = SLOT_W * SLOTS_PER_ZONE
    const tint = new THREE.Mesh(
      track(new THREE.PlaneGeometry(width + 4, SLOT_DEPTH + 4)),
      track(
        new THREE.MeshBasicMaterial({
          color: zone.cold ? COLORS.cold : 0x1f3a55,
          transparent: true,
          opacity: zone.cold ? 0.12 : 0.35,
        }),
      ),
    )
    tint.rotation.x = -Math.PI / 2
    tint.position.set(zone.x0 + width / 2, 0.06, SLOT_Z0 + SLOT_DEPTH / 2)
    scene.add(tint)
    const points: THREE.Vector3[] = []
    for (let i = 0; i <= SLOTS_PER_ZONE; i++) {
      const x = zone.x0 + i * SLOT_W
      points.push(new THREE.Vector3(x, 0.1, SLOT_Z0), new THREE.Vector3(x, 0.1, SLOT_Z0 + SLOT_DEPTH))
    }
    points.push(
      new THREE.Vector3(zone.x0, 0.1, SLOT_Z0 + SLOT_DEPTH),
      new THREE.Vector3(zone.x0 + width, 0.1, SLOT_Z0 + SLOT_DEPTH),
    )
    scene.add(
      new THREE.LineSegments(
        track(new THREE.BufferGeometry().setFromPoints(points)),
        zone.cold ? mat.coldLine : mat.slotLine,
      ),
    )
    if (zone.cold) {
      // tomada do baú refrigerado: o que diferencia a vaga de cadeia fria
      for (let i = 0; i < SLOTS_PER_ZONE; i++) {
        const post = addBox(0.5, 1.8, 0.5, mat.building, slotX(2, i), 0.9, SLOT_Z0 + SLOT_DEPTH + 1.2)
        const led = new THREE.Mesh(
          track(new THREE.SphereGeometry(0.28, 10, 10)),
          track(new THREE.MeshBasicMaterial({ color: COLORS.cold })),
        )
        led.position.y = 1.1
        post.add(led)
      }
    }
  })

  /* ---------------- caminhões ---------------- */
  const wheelGeo = track(new THREE.CylinderGeometry(0.55, 0.55, 0.5, 14))
  wheelGeo.rotateX(Math.PI / 2)
  const makeTruck = (reefer: boolean) => {
    const truck = new THREE.Group()
    addBox(2.8, 3, 2.6, mat.cab, 5.2, 2, 0, truck) // cavalo (frente em +X)
    addBox(0.2, 1.2, 2.3, mat.glass, 6.65, 2.6, 0, truck) // para-brisa
    addBox(10.2, 3.6, 2.6, reefer ? mat.reefer : mat.trailer, -1.6, 2.6, 0, truck)
    addBox(10.3, 0.35, 2.65, reefer ? mat.coldStripe : mat.brand, -1.6, 1.3, 0, truck)
    for (const x of [5.4, 1.2, -4.4, -5.6]) {
      for (const z of [1.25, -1.25]) {
        const wheel = new THREE.Mesh(wheelGeo, mat.tire)
        wheel.position.set(x, 0.55, z)
        truck.add(wheel)
      }
    }
    const beacon = new THREE.Mesh(
      track(new THREE.SphereGeometry(0.3, 10, 10)),
      track(new THREE.MeshBasicMaterial({ color: COLORS.ok })),
    )
    beacon.position.set(5.2, 3.8, 0)
    truck.add(beacon)
    truck.userData.beacon = beacon
    scene.add(truck)
    return truck
  }

  const place = (truck: THREE.Group, x: number, z: number, heading: number) => {
    truck.position.set(x, 0, z)
    truck.rotation.y = heading
  }

  // Estacionados: o pátio da demonstração nunca está vazio.
  const parked: [number, number][] = [
    [0, 1], [0, 3], [0, 6], [1, 0], [1, 2], [1, 5], [1, 7], [2, 1], [2, 4], [2, 6],
  ]
  parked.forEach(([zone, i]) => {
    const truck = makeTruck(zone === 2)
    place(truck, slotX(zone, i), SLOT_Z0 + 10, -Math.PI / 2)
  })
  // Encostados: docas ocupadas com porta aberta.
  const busyDocks = [2, 5, 9, 12]
  busyDocks.forEach((d) => {
    const truck = makeTruck(d === 9)
    place(truck, DOCK_X(d), DOOR_Z + 8.5, -Math.PI / 2)
    doors[d]!.scale.y = 0.15
    ;(doorLights[d]!.material as THREE.MeshBasicMaterial).color.set(COLORS.warn)
  })

  /* ---------------- ciclo animado ---------------- */
  const heading = (from: THREE.Vector3, to: THREE.Vector3) => Math.atan2(-(to.z - from.z), to.x - from.x)
  const shortest = (from: number, to: number) => {
    let delta = (to - from) % (Math.PI * 2)
    if (delta > Math.PI) delta -= Math.PI * 2
    if (delta < -Math.PI) delta += Math.PI * 2
    return from + delta
  }
  const V = (x: number, z: number) => new THREE.Vector3(x, 0, z)

  /** Anda por uma curva; `reverse` = de ré (a frente aponta contra o movimento). */
  const drive = (
    tl: gsap.core.Timeline,
    truck: THREE.Group,
    points: THREE.Vector3[],
    speed: number,
    reverse = false,
  ) => {
    const curve = new THREE.CatmullRomCurve3(points, false, 'centripetal')
    const length = curve.getLength()
    const state = { t: 0 }
    const start = curve.getTangentAt(0)
    const startHeading = heading(V(0, 0), V(start.x, start.z)) + (reverse ? Math.PI : 0)
    // alinha antes de sair: caminhão não gira no lugar a 40 km/h
    tl.to(truck.rotation, {
      y: () => shortest(truck.rotation.y, startHeading),
      duration: 0.5,
      ease: 'power1.inOut',
    })
    tl.to(state, {
      t: 1,
      duration: length / speed,
      ease: 'power1.inOut',
      onUpdate: () => {
        const point = curve.getPointAt(state.t)
        const tangent = curve.getTangentAt(state.t)
        truck.position.set(point.x, 0, point.z)
        const h = Math.atan2(-tangent.z, tangent.x) + (reverse ? Math.PI : 0)
        truck.rotation.y = shortest(truck.rotation.y, h)
      },
    })
  }

  const beacon = (truck: THREE.Group, color: number) => () =>
    (truck.userData.beacon.material as THREE.MeshBasicMaterial).color.set(color)

  const timelines: gsap.core.Timeline[] = []
  const cycle = (index: number, zone: number, slot: number, dock: number, reefer: boolean) => {
    const truck = makeTruck(reefer)
    place(truck, -270, ROAD_Z + 3, 0)
    truck.visible = false
    const sx = slotX(zone, slot)
    const dx = DOCK_X(dock)
    const lane = ROAD_Z + 3.5
    const tl = gsap.timeline({ repeat: -1, delay: index * 7.5, repeatDelay: 2 })
    tl.call(() => {
      truck.visible = true
      place(truck, -270, lane, 0)
      beacon(truck, COLORS.warn)()
    })
    drive(tl, truck, [V(-270, lane), V(-220, lane), V(GATE_IN_X - 14, lane)], 34)
    // portaria: LPR lê, checklist ok, cancela abre
    tl.to(gateArm.rotation, { x: Math.PI / 2.2, duration: 0.7, ease: 'power2.out' }, '+=0.6')
    tl.call(beacon(truck, COLORS.ok))
    drive(tl, truck, [V(GATE_IN_X - 14, lane), V(GATE_IN_X + 10, lane), V(SCALE_X, lane)], 22)
    tl.to(gateArm.rotation, { x: 0, duration: 0.8, ease: 'power2.inOut' }, '<0.6')
    // balança: peso assenta, ticket fecha
    tl.to(scaleFrame.material as THREE.LineBasicMaterial, { opacity: 0.2, duration: 0.2, yoyo: true, repeat: 5 })
    tl.to(mat.display.emissive, { r: 0.95, g: 0.55, b: 0.16, duration: 0.3 }, '<')
    tl.to(mat.display.emissive, { r: 0.04, g: 0.31, b: 0.42, duration: 0.5 }, '+=0.6')
    // vaga: entra de frente, espera a doca
    drive(tl, truck, [V(SCALE_X, lane), V(sx - 22, lane), V(sx - 6, lane + 2), V(sx, SLOT_Z0 + 2), V(sx, SLOT_Z0 + 10)], 18)
    tl.call(beacon(truck, COLORS.warn))
    tl.to({}, { duration: 3.2 })
    tl.call(beacon(truck, COLORS.ok))
    // sai de ré até a via, segue para o pátio das docas e encosta de ré
    // (de ré até ficar de frente para leste; depois paralelo ao armazém e ré a 90°)
    drive(tl, truck, [V(sx, SLOT_Z0 + 10), V(sx, SLOT_Z0 - 6), V(sx - 4, lane - 1), V(sx - 12, lane - 2)], 8, true)
    drive(
      tl,
      truck,
      [V(sx - 12, lane - 2), V(sx + 4, ROAD_Z - 1), V(sx + 16, 34), V(sx + 26, 22), V(dx + 2, 13), V(dx + 16, 12)],
      18,
    )
    drive(tl, truck, [V(dx + 16, 12), V(dx + 6, 10), V(dx + 0.5, 1), V(dx, DOOR_Z + 8.5)], 6, true)
    tl.to(doors[dock]!.scale, { y: 0.15, duration: 0.8, ease: 'power2.out' })
    tl.call(() => (doorLights[dock]!.material as THREE.MeshBasicMaterial).color.set(COLORS.warn), undefined, '<')
    tl.to({}, { duration: 4.5 })
    tl.to(doors[dock]!.scale, { y: 1, duration: 0.8, ease: 'power2.inOut' })
    tl.call(() => (doorLights[dock]!.material as THREE.MeshBasicMaterial).color.set(COLORS.ok), undefined, '<')
    // saída
    drive(tl, truck, [V(dx, DOOR_Z + 8.5), V(dx, 22), V(dx + 12, ROAD_Z - 3.5), V(GATE_OUT_X - 14, ROAD_Z - 3.5)], 20)
    tl.to(exitArm.rotation, { x: -Math.PI / 2.2, duration: 0.7, ease: 'power2.out' }, '+=0.4')
    drive(tl, truck, [V(GATE_OUT_X - 14, ROAD_Z - 3.5), V(GATE_OUT_X + 20, ROAD_Z - 3.5), V(290, ROAD_Z - 3.5)], 30)
    tl.to(exitArm.rotation, { x: 0, duration: 0.8 }, '<1')
    tl.call(() => {
      truck.visible = false
    })
    timelines.push(tl)
  }

  const routes: [number, number, number][] = options.lowPower
    ? [[0, 2, 4], [1, 4, 8], [2, 3, 13]]
    : [[0, 2, 4], [1, 4, 8], [2, 3, 13], [0, 5, 6], [1, 1, 7], [2, 0, 10]]
  if (!options.reducedMotion) {
    routes.forEach(([zone, slot, dock], i) => cycle(i, zone, slot, dock, zone === 2))
  }

  /* ---------------- camada de gêmeo digital ---------------- */
  const beams: THREE.Mesh[] = []
  const rings: THREE.Mesh[] = []
  const ringGeo = track(new THREE.RingGeometry(3.2, 3.8, 48))
  const beamGeo = track(new THREE.CylinderGeometry(0.18, 0.18, 1, 8, 1, true))
  ;(Object.keys(HOTSPOTS) as HotspotId[]).forEach((id) => {
    const point = HOTSPOTS[id]
    const color = id === 'cold' ? COLORS.cold : COLORS.brand
    const beam = new THREE.Mesh(
      beamGeo,
      track(new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.35, depthWrite: false })),
    )
    beam.scale.y = point.y
    beam.position.set(point.x, point.y / 2, point.z)
    beam.userData.id = id
    scene.add(beam)
    beams.push(beam)
    const ring = new THREE.Mesh(
      ringGeo,
      track(
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: 0.6,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      ),
    )
    ring.rotation.x = -Math.PI / 2
    ring.position.set(point.x, 0.15, point.z)
    ring.userData.id = id
    scene.add(ring)
    rings.push(ring)
    if (!options.reducedMotion) {
      gsap.fromTo(
        ring.scale,
        { x: 0.6, y: 0.6 },
        { x: 2.2, y: 2.2, duration: 2.4, repeat: -1, ease: 'power1.out' },
      )
      gsap.fromTo(
        ring.material as THREE.MeshBasicMaterial,
        { opacity: 0.7 },
        { opacity: 0, duration: 2.4, repeat: -1, ease: 'power1.out' },
      )
    }
  })

  // varredura: a "leitura" do gêmeo passando pelo pátio
  const scan = new THREE.Mesh(
    track(new THREE.PlaneGeometry(6, 420)),
    track(
      new THREE.MeshBasicMaterial({
        color: COLORS.edge,
        transparent: true,
        opacity: 0.12,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    ),
  )
  scan.rotation.x = -Math.PI / 2
  scan.position.set(-260, 0.3, 20)
  scene.add(scan)
  if (!options.reducedMotion) {
    gsap.to(scan.position, { x: 260, duration: 9, repeat: -1, ease: 'none' })
  } else {
    scan.visible = false
  }


  /* ---------------- painéis holográficos ---------------- */
  // Desenhados em canvas e atualizados ao vivo: KPIs junto à torre e um Gantt de docas
  // flutuando sobre o armazém. Só números e barras — o texto humano fica no HTML.
  const makePanel = (w: number, h: number, pxW: number, pxH: number) => {
    const surface = document.createElement('canvas')
    surface.width = pxW
    surface.height = pxH
    const texture = track(new THREE.CanvasTexture(surface))
    texture.colorSpace = THREE.SRGBColorSpace
    const panel = new THREE.Mesh(
      track(new THREE.PlaneGeometry(w, h)),
      track(
        new THREE.MeshBasicMaterial({
          map: texture,
          transparent: true,
          side: THREE.DoubleSide,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        }),
      ),
    )
    scene.add(panel)
    return { panel, ctx: surface.getContext('2d') as CanvasRenderingContext2D, texture, pxW, pxH }
  }
  const frame = (c: CanvasRenderingContext2D, w: number, h: number) => {
    c.clearRect(0, 0, w, h)
    c.fillStyle = 'rgba(10, 60, 90, 0.35)'
    c.fillRect(0, 0, w, h)
    c.strokeStyle = 'rgba(76, 201, 240, 0.9)'
    c.lineWidth = 3
    c.strokeRect(2, 2, w - 4, h - 4)
    c.fillStyle = 'rgba(242, 140, 40, 0.95)'
    c.fillRect(2, 2, 90, 8)
  }

  const kpi = makePanel(46, 28, 512, 312)
  kpi.panel.position.set(-112, 36, -22)
  kpi.panel.rotation.y = -0.55
  const trend = Array.from({ length: 28 }, (_, i) => 55 + Math.sin(i / 3) * 12)
  const bars = [0.72, 0.58, 0.83, 0.41]
  const drawKpi = () => {
    const { ctx: c, pxW: w, pxH: h } = kpi
    frame(c, w, h)
    c.font = '600 40px Inter, system-ui, sans-serif'
    const values = ['38', '8', '24', '91%']
    values.forEach((value, i) => {
      c.fillStyle = i === 3 ? '#ffb15c' : '#eaf1f7'
      c.fillText(value, 24 + i * 122, 70)
    })
    bars.forEach((value, i) => {
      const y = 104 + i * 30
      c.fillStyle = 'rgba(76, 201, 240, 0.18)'
      c.fillRect(24, y, w - 48, 14)
      c.fillStyle = value > 0.8 ? '#f28c28' : '#4cc9f0'
      c.fillRect(24, y, (w - 48) * value, 14)
    })
    c.beginPath()
    trend.forEach((value, i) => {
      const x = 24 + (i / (trend.length - 1)) * (w - 48)
      const y = h - 24 - (value / 100) * 70
      if (i === 0) c.moveTo(x, y)
      else c.lineTo(x, y)
    })
    c.strokeStyle = '#34d399'
    c.lineWidth = 3
    c.stroke()
    kpi.texture.needsUpdate = true
  }

  const gantt = makePanel(96, 26, 1024, 278)
  gantt.panel.position.set(10, 40, -30)
  const lanes = Array.from({ length: 7 }, (_, i) => ({ offset: i * 97, length: 160 + ((i * 53) % 140) }))
  let ganttShift = 0
  const drawGantt = () => {
    const { ctx: c, pxW: w, pxH: h } = gantt
    frame(c, w, h)
    const rowH = (h - 40) / lanes.length
    lanes.forEach((lane, i) => {
      const y = 28 + i * rowH
      c.fillStyle = 'rgba(76, 201, 240, 0.12)'
      c.fillRect(20, y, w - 40, rowH - 8)
      for (let k = 0; k < 4; k++) {
        const x = ((lane.offset + k * 260 - ganttShift) % (w + 200)) - 100
        c.fillStyle = (i + k) % 5 === 0 ? 'rgba(242, 140, 40, 0.95)' : 'rgba(76, 201, 240, 0.8)'
        c.fillRect(Math.max(20, x), y + 3, Math.max(0, Math.min(lane.length, w - 20 - x)), rowH - 14)
      }
    })
    // "agora": linha vertical fixa
    c.fillStyle = '#34d399'
    c.fillRect(w * 0.62, 18, 3, h - 30)
    gantt.texture.needsUpdate = true
  }
  drawKpi()
  drawGantt()
  const holoTimer = options.reducedMotion
    ? 0
    : window.setInterval(() => {
        if (!visible) return
        trend.shift()
        trend.push(50 + Math.random() * 30)
        bars.forEach((value, i) => (bars[i] = THREE.MathUtils.clamp(value + (Math.random() - 0.5) * 0.08, 0.25, 0.95)))
        ganttShift = (ganttShift + 6) % 100000
        drawKpi()
        drawGantt()
      }, 450)

  /* ---------------- câmera ---------------- */
  const posCurve = new THREE.CatmullRomCurve3(
    SHOTS.map((shot) => new THREE.Vector3(...shot.pos)),
    false,
    'centripetal',
  )
  const targets = SHOTS.map((shot) => new THREE.Vector3(...shot.target))
  const lookAt = new THREE.Vector3()
  const camState = { p: 0 }
  const idle = { angle: 0 }
  if (!options.reducedMotion) {
    gsap.to(idle, { angle: Math.PI * 2, duration: 60, repeat: -1, ease: 'none' })
  }

  const applyCamera = () => {
    const p = THREE.MathUtils.clamp(camState.p, 0, 1)
    camera.position.copy(posCurve.getPointAt(p))
    const segment = p * (targets.length - 1)
    const i = Math.min(Math.floor(segment), targets.length - 2)
    const local = THREE.MathUtils.smoothstep(segment - i, 0, 1)
    lookAt.lerpVectors(targets[i]!, targets[i + 1]!, local)
    // respiração leve na abertura: a cena parece viva antes da primeira rolagem
    const sway = (1 - Math.min(p * 6, 1)) * 18
    camera.position.x += Math.sin(idle.angle) * sway
    camera.position.z += Math.cos(idle.angle) * sway * 0.5
    camera.lookAt(lookAt)
  }

  let active: HotspotId | null = null
  const setActive = (id: HotspotId | null) => {
    active = id
    beams.forEach((beam) => {
      const on = !id || beam.userData.id === id
      gsap.to(beam.material as THREE.MeshBasicMaterial, { opacity: on ? 0.45 : 0.08, duration: 0.5 })
    })
  }

  /* ---------------- laço ---------------- */
  const resize = () => {
    const { clientWidth: w, clientHeight: h } = canvas
    if (!w || !h) return
    renderer.setSize(w, h, false)
    camera.aspect = w / h
    // retrato (celular): abre o ângulo para o pátio caber
    camera.fov = w / h < 0.8 ? 58 : 38
    camera.updateProjectionMatrix()
  }
  const observer = new ResizeObserver(resize)
  observer.observe(canvas)
  resize()

  const io = new IntersectionObserver(([entry]) => (visible = entry?.isIntersecting ?? true))
  io.observe(canvas)

  const tick = () => {
    if (!visible) return
    applyCamera()
    renderer.render(scene, camera)
  }
  gsap.ticker.add(tick)

  const projected = new THREE.Vector3()
  return {
    setProgress: (progress) => {
      gsap.to(camState, {
        p: progress,
        duration: options.reducedMotion ? 0 : 0.9,
        ease: 'power2.out',
        overwrite: true,
      })
    },
    hotspots: () =>
      (Object.keys(HOTSPOTS) as HotspotId[]).map((id) => {
        projected.copy(HOTSPOTS[id]).project(camera)
        return {
          id,
          x: (projected.x * 0.5 + 0.5) * canvas.clientWidth,
          y: (-projected.y * 0.5 + 0.5) * canvas.clientHeight,
          visible: projected.z < 1 && Math.abs(projected.x) < 1.05 && Math.abs(projected.y) < 1.05,
          active: active === id,
        }
      }),
    setActive,
    dispose: () => {
      gsap.ticker.remove(tick)
      window.clearInterval(holoTimer)
      timelines.forEach((tl) => tl.kill())
      gsap.killTweensOf([scan.position, idle, camState])
      observer.disconnect()
      io.disconnect()
      disposables.forEach((item) => item.dispose())
      renderer.dispose()
    },
  }
}
