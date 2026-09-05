# Preguntas frecuentes

*(English version: [faq.md](faq.md))*

**¿Necesito GPU?**
Solo para la vía del vídeo (MapAnything). `levanta plan` sobre una nube de puntos,
`levanta tum`, `levanta site`, `levanta render` y `levanta demo` corren en cualquier
portátil. Sin GPU CUDA, MapAnything corre en CPU, pero cuenta con muchos minutos por
vista y más de 8 GB de RAM.

**¿Qué móvil sirve?**
Cualquiera. levanta solo necesita el archivo de vídeo. Quien tenga iPhone Pro o iPad Pro
con LiDAR puede además exportar RGB-D con poses desde apps como Record3D y darle a
`levanta plan` una nube métrica, lo que elimina del todo la duda de la escala.

**¿Cómo abro los resultados?**
Doble clic en `plan.html`: tiene el plano 2D, una vista 3D interactiva y una tabla de
medidas. `plan.png` es para mandar por WhatsApp; `plan.svg` para editar en
Inkscape/Illustrator; `plan.dxf` para AutoCAD, LibreCAD, SketchUp; `plan.glb` para
Blender, el Visor 3D de Windows o cualquier visor web; `plan.json` para programas.

**El plano dice «incompleta» en una habitación.**
Un lado de la habitación no se vio como pared del suelo al techo. El contorno por ese
lado sigue el suelo que vio la cámara y va dibujado a trazos. Vuelve a grabar esa pared
(ver la guía de captura) o acepta el contorno.

**No sale ninguna habitación.**
Abre `plan_debug.png`. Gris es donde miró la cámara, los puntos negros son puntos de
pared, los rectángulos de color son paredes detectadas, verde es una habitación. Si no
hay rectángulos de color, las paredes no se escanearon del suelo al techo; si hay
paredes pero no verde, la habitación no está cerrada por tres lados y el suelo no se vio.

**El plano sale girado / en espejo.**
El marco del plano se alinea con las paredes (marco Manhattan), no con el norte. Gíralo
en tu programa de CAD. Un espejo no puede pasar; si lo parece, lo estás mirando desde
abajo en el visor 3D.

**Paredes donde no hay.**
Armarios, neveras, puertas abiertas y estanterías que llegan cerca del techo son
indistinguibles de una pared para un escáner. Cierra las puertas y borra la pared sobrante
en `plan.json` (quítala de `walls`), luego `levanta render plan.json`.

**Las medidas salen un poco pequeñas.**
La escala solo desde vídeo suele quedarse corta un 5–15 %. Pasa `--focal-px`, o mide una
puerta y usa `--door-width 0.90` (también funciona después con `levanta render`).

**¿Sirve para varias plantas?**
Graba una planta por vídeo y ejecuta levanta una vez por planta. Las escaleras no se
modelan.

**¿Puede sacar el interior de Google Maps / satélite?**
No, y nada puede: ningún sensor ve a través del techo. `levanta site` da lo que sí
contienen los datos cenitales, huella y altura, como un bloque LOD1.

**¿Mis datos se suben a algún sitio?**
No. Todo corre en tu máquina. El único acceso a red es la descarga opcional de los pesos
del modelo (HuggingFace) y las APIs públicas de mapas de `levanta site`.

**¿Puedo usarlo comercialmente?**
Sí. Licencia MIT: conserva el aviso de copyright.
