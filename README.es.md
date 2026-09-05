# levanta

**Graba tu casa con el móvil y obtén el plano y un modelo 3D.** También funciona desde
una nube de puntos, desde fotogramas RGB-D y, para el exterior de cualquier edificio,
desde datos públicos de mapas. Librería de Python y herramienta de línea de comandos.
MIT: conserva el aviso del autor y es tuya para usarla, venderla o construir encima.

*[English README](README.md)*

<p align="center">
  <img src="examples/synthetic_three_rooms/plan.png" width="720" alt="Plano 2D generado por levanta: tres habitaciones, puertas con abatimiento, ventanas, cotas">
</p>
<p align="center">
  <img src="examples/synthetic_three_rooms/plan_3d.png" width="520" alt="Vista 3D del mismo plano: paredes con huecos de puertas y ventanas, losas de suelo">
</p>

## Pruébalo en diez segundos

```bash
pip install git+https://github.com/EazyHood/levanta
levanta demo --lang es --open
```

Construye un apartamento pequeño tal como lo vería un móvil, pasa toda la tubería y
abre `plan.html`: el plano 2D, una vista 3D que puedes girar y una tabla con cada
medida. Sin GPU, sin datos y sin internet salvo para el `pip`.

## Después, tu casa

1. **Grábala.** Despacio, en horizontal, cada pared del suelo al techo, a través de cada
   puerta. Diez minutos leyendo [la guía de captura](docs/guia-de-captura.md) ahorran
   una hora después.
2. **Comprueba el vídeo** antes de gastar GPU:
   ```bash
   levanta check recorrido.mp4
   ```
3. **Ejecuta** (necesita los extras de GPU, ver *Instalación*):
   ```bash
   levanta video recorrido.mp4 -o out/casa --lang es --names "Sala,Cocina,Dormitorio,Baño" --open
   ```
4. **Corrige la escala** si las puertas salen estrechas. Mide una puerta y:
   ```bash
   levanta render out/casa/plan.json --lang es --door-width 0.90
   ```

Obtienes, en `out/casa/`: `plan.html` · `plan.png` · `plan.svg` · `plan_3d.png` ·
`plan.dxf` (CAD) · `plan.glb` / `plan.obj` (3D) · `plan.json` (datos) · `plan_debug.png`
(lo que vio el planificador). [Qué es cada archivo y con qué se abre.](docs/formats.md)

## Qué hace, sin adornos

| Entrada | Qué obtienes | Cómo |
|---|---|---|
| **Vídeo del móvil** | Nube de puntos métrica, paredes con grosor, puertas, ventanas, habitaciones con áreas, altura de techo, plano 2D, modelo 3D | MapAnything (Meta, 3DV 2026) predice profundidad métrica y cámaras a partir de RGB; `levanta.plan` convierte la nube en arquitectura |
| **Fotogramas RGB-D con poses** (exportaciones de ARCore/ARKit/Record3D, datasets) | Lo mismo, sin GPU, escala exacta | retroproyección en numpy |
| **Nube de puntos** en metros (`.ply`) | Lo mismo | `levanta plan` |
| **Una latitud/longitud** | Huella del edificio, altura, modelo de bloque LOD1, plano de sitio con la longitud de cada lado | OpenStreetMap u Overture Maps, ambos derivados de imágenes cenitales |

Lo que un satélite **no puede** darte es el interior: ningún sensor ve a través del
techo. Por eso `levanta site` se detiene en huella + altura, y su salida lo dice. El
plano interior sale de recorrer la casa.

## Instalación

```bash
pip install git+https://github.com/EazyHood/levanta            # planos, 3D, modelos de sitio (sin GPU)
pip install "levanta[overture] @ git+https://github.com/EazyHood/levanta"   # + fuente Overture Maps
```

Para la vía del vídeo hace falta además PyTorch con CUDA y MapAnything (Apache-2.0):

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128   # elige tu CUDA en pytorch.org
pip install -r requirements-recon.txt
levanta doctor                                                                     # te dice qué falta
```

Python 3.10 o superior. Windows, Linux y macOS para todo salvo la vía de GPU, que
necesita una NVIDIA de 8 GB o más (24–32 fotogramas) o paciencia en CPU. La primera
ejecución con vídeo descarga 4,6 GB de pesos una sola vez.

## Todos los comandos

```
levanta demo                       verlo funcionar sobre un apartamento sintético
levanta check  recorrido.mp4       ¿sirve el vídeo?
levanta video  recorrido.mp4 -o out    vídeo -> plano + 3D (GPU)
levanta plan   nube.ply -o out     nube de puntos -> plano + 3D
levanta tum    <secuencia> -o out  secuencia pública TUM RGB-D -> plano (sin GPU)
levanta site   --lat 4.5981 --lon -74.0760 -o out     coordenada -> huella, altura, LOD1
levanta render plan.json           rehacer todas las salidas tras editar el JSON
levanta doctor                     instalado / falta / qué escribir
```

Opciones comunes: `--lang es`, `--units ft`, `--names "A,B,C"`, `--title "..."`,
`--open`, `--door-width 0.90`, `--scale 1.07`, `--ceiling`. Cada comando escribe un
`*_debug.png`.

Como librería:

```python
from levanta import PointCloud, extract_floor_plan, PlanOptions
from levanta.io.export import export_all

cloud = PointCloud.load_ply("nube.ply")                # metros; usa normales y cámaras si existen
result = extract_floor_plan(cloud, PlanOptions())
plan = result.plan.rename_rooms(["Sala", "Cocina"])
plan, factor = plan.calibrated_to_door_width(0.90)     # corrección de escala opcional
export_all(plan, "out", lang="es", units="m")           # html, png, svg, dxf, glb, obj, json
```

## Cómo funciona

1. **Reconstrucción** (`levanta.recon`). Los fotogramas RGB-D se retroproyectan con
   normales calculadas sobre la imagen de profundidad (base de 6 píxeles más un filtro
   de mediana, porque la profundidad de consumo tiene ruido de centímetros) y orientadas
   hacia la cámara. Para vídeo plano, MapAnything predice en una pasada la profundidad
   métrica, los intrínsecos y las poses de cada vista; esas vistas pasan por el mismo
   código. Cada punto recuerda qué cámara lo vio.
2. **Gravedad** (`levanta.plan.gravity`). El «arriba» medio de las cámaras siembra una
   vertical que se afina con las normales de suelo y techo; un histograma de alturas da
   el suelo y el techo.
3. **Marco Manhattan** (`levanta.plan.walls`). La moda de los ángulos de las normales de
   pared, plegados a 90°, rota la nube para que las paredes vayan por x e y. `--free`
   conserva cualquier dirección.
4. **Rásteres** (`levanta.plan.occupancy`). Por celda, cuántas bandas de altura contienen
   puntos de pared: una pared va del suelo al techo, un sofá no. Las líneas de visión
   cámara-punto marcan el espacio libre: un hueco por el que pasaron rayos es una
   puerta; uno que ningún rayo cruzó es pared que nadie miró.
5. **Caras → paredes.** Por dirección, el histograma de desplazamientos da los planos de
   pared; las rachas de puntos a lo largo de cada plano dan caras; una cara vista desde
   la habitación del otro lado se empareja con ella, y eso *mide* el grosor. Las caras
   solitarias reciben un grosor por defecto y cuentan como exteriores cuando nunca se vio
   nada detrás.
6. **Huecos.** Los vanos con línea de visión son puertas (pasos si superan 1,3 m), con la
   altura del dintel medida; los bordes de puertas y ventanas se afinan a 1 cm sobre las
   muestras crudas. Las ventanas son tramos vistos por debajo y por encima de una banda
   pero nunca dentro.
7. **Habitaciones** (`levanta.plan.rooms`). Se tapian las puertas temporalmente y los
   huecos entre cuerpos de pared son las habitaciones. Se puentean vanos de hasta 1,2 m;
   lo que sigue abierto sigue el suelo visto, recibe un contorno rectilíneo y la marca
   `closed: false`.
8. **Dibujos y 3D** (`levanta.io`). Un único modelo de dibujo genera el SVG y el PNG, así
   que siempre coinciden. Las paredes son cajas partidas alrededor de los huecos (cajas
   de antepecho y dintel, sin booleanas); la vista 3D es una proyección axonométrica
   dibujada sin OpenGL.

## Cómo sabemos que funciona

Los tests construyen apartamentos con verdad exacta (`levanta.synthetic`): muestras con
ruido de paredes, suelo y techo, muebles bajos, cámaras que ven a través de las puertas,
una copia inclinada y girada. Los umbrales de aceptación se escribieron antes de la
primera ejecución.

| Magnitud | Verdad | Medido | Umbral |
|---|---|---|---|
| IoU de área por habitación (5 habitaciones, 2 escenas) | 1,0 | ≥ 0,999 | ≥ 0,90 |
| Grosor de pared interior | 0,120 m | 0,119 m | ± 0,03 m |
| Ancho de puertas (4) | 0,90 m | 0,87–0,89 m | ± 0,20 m |
| Ancho de ventanas / antepecho / dintel | 1,20 y 1,40 m / 0,90 / 2,10 | 1,19 y 1,39 m / 0,85 / 2,10 | ± 0,20 / ± 0,10 m |
| Altura de techo | 2,50 m | 2,4998 m | ± 0,03 m |
| Residuo Manhattan tras 23° de giro + 9° de inclinación | 0° | < 0,1° | < 1° |

**Datos reales**, TUM `freiburg1_room` (una Kinect en mano recorriendo una oficina llena
de mesas, poses de captura de movimiento, 454 fotogramas, sin GPU): aparecen tres
paredes, la puerta (0,83 m, dintel medido a 2,54 m) y el techo (2,91 m); la habitación
sale de 5,0 × 5,0 m. La cuarta pared es de cristal y nunca devolvió profundidad, así que
por ese lado el contorno sigue el suelo visto y la habitación queda marcada como
incompleta. Ver [`examples/tum_fr1_room/`](examples/tum_fr1_room/).

<p align="center">
  <img src="examples/tum_fr1_room/plan.png" width="520" alt="Plano de la oficina TUM fr1_room: tres paredes, una puerta, un lado a trazos por no escaneado">
</p>

**MapAnything solo con RGB** sobre la misma secuencia (16 fotogramas de 640×480, portátil
con RTX 5060 de 8 GB, 6,7 GB de VRAM, 46 s con los pesos en caché), comparado píxel a
píxel con la profundidad de la Kinect:

| Entradas a la red | mediana profundidad predicha / Kinect | error abs-rel |
|---|---|---|
| solo imágenes | 0,86 | 0,14 |
| imágenes + intrínsecos conocidos | **0,93** | **0,095** |

Es decir, la escala desde vídeo a secas se queda corta un 7–14 %. Para eso están
`--focal-px` y `--door-width`. Veinte fotogramas de una Kinect a 640×480 son un caso
duro para el planificador (dos paredes y una habitación abierta); la entrada prevista
es un móvil a 1080p con más de 30 fotogramas.

## Límites que conviene saber

- **La escala desde vídeo** vale lo que vale la estimación métrica de la red: pasa la
  focal o calibra con una puerta. RGB-D con poses del dispositivo es exacto.
- **Un mueble alto parece una pared.** Armarios, neveras y hojas de puerta abiertas
  llegan lo bastante alto como para pasar la prueba de altura. Escanea con las puertas
  cerradas; borra la pared sobrante en el JSON y `levanta render`.
- **Lo no visto es desconocido.** El grosor se mide solo donde se escanearon las dos
  caras; si no, se usa un valor por defecto (`sides_seen: 1`). Las habitaciones con un
  lado sin escanear se dibujan a trazos por ahí y se etiquetan *incompleta*, nunca se
  inventan.
- **El modo Manhattan** ajusta las paredes a dos direcciones; `--free` para paredes en
  ángulo.
- **Los modelos de sitio son LOD1**: huella × altura. La altura sale de la etiqueta
  `height` de la fuente si existe, si no de `plantas × 3 m`, si no 3 m, y el JSON dice
  cuál.
- Cristales, espejos y paredes lisas son difíciles para cualquier fotogrametría.

Más en las [preguntas frecuentes](docs/preguntas-frecuentes.md).

## Datos y licencias usados

- [MapAnything](https://github.com/facebookresearch/map-anything), código Apache-2.0; el
  checkpoint por defecto `facebook/map-anything-apache` también es Apache-2.0.
- [TUM RGB-D benchmark](https://cvg.cit.tum.de/data/datasets/rgbd-dataset), CC BY 4.0
  (Sturm et al., IROS 2012). No se redistribuye; `levanta tum` lee una secuencia
  descargada.
- [OpenStreetMap](https://www.openstreetmap.org) vía Overpass, ODbL 1.0,
  © colaboradores de OpenStreetMap. [Overture Maps](https://overturemaps.org), ODbL /
  CDLA-Permissive-2.0 según la fuente.
- El visor HTML carga [three.js](https://threejs.org) (MIT) desde un CDN para la vista 3D
  interactiva; todo lo demás va embebido en el archivo.

## Estructura

```
src/levanta/
  scene.py, geometry.py    Camera, Frame, PointCloud; ayudas numéricas
  synthetic.py             apartamentos con verdad exacta (tests y `levanta demo`)
  i18n.py                  etiquetas en inglés y español, metros o pies
  io/                      fotogramas de vídeo y su comprobación, lector TUM, modelo de dibujo (SVG+PNG),
                           plano 2D, 3D axonométrico, visor HTML, escritores DXF/GLB/OBJ/JSON
  recon/                   retroproyección RGB-D, adaptador MapAnything
  plan/                    gravedad, rásteres, paredes, habitaciones y huecos, pipeline, modelo 3D, PNG de diagnóstico
  site/                    proyección WGS84, fuentes OSM/Overture, modelo LOD1 + plano de sitio
  cli.py                   el comando `levanta`
tests/                     escenas con verdad exacta, tests unitarios, tests del CLI (sin GPU ni red)
docs/                      guía de captura, preguntas frecuentes, formatos (inglés y español)
examples/                  salidas que se pueden abrir sin ejecutar nada
```

## Licencia y autoría

MIT, ver [LICENSE](LICENSE). Copyright (c) 2026 Jhona (github.com/EazyHood). Úsala,
cópiala, modifícala, véndela: solo conserva el aviso de copyright y el de permiso junto
a ella. En trabajos publicados se agradece la cita ([CITATION.cff](CITATION.cff)).
