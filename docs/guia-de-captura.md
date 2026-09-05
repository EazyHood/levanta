# Cómo grabar una casa para que el plano salga bien

*(English version: [capture-guide.md](capture-guide.md))*

levanta reconstruye lo que la cámara **vio**. Nada más, nada inventado. Así que todo
consiste en cubrir: cada pared, del suelo al techo, desde dentro de la habitación, y una
mirada a través de cada puerta. Diez minutos de cuidado aquí ahorran una hora
preguntándote por qué falta una pared.

## Antes de empezar

- **Puertas abiertas, armarios cerrados.** La puerta abierta de un armario, o un
  ropero, parecen una pared.
- **Luces encendidas, cortinas abiertas.** El desenfoque y la oscuridad son el enemigo;
  la red necesita textura.
- **Despeja el borde del suelo** si puedes. El planificador encuentra las habitaciones por
  el suelo que ve.
- Móvil en **horizontal**, 1080p o más, lente normal (ni gran angular ni zoom).
- Limpia la lente.

## El recorrido

1. Ponte en el centro de la habitación. **Gira despacio** (una vuelta completa en unos
   20 segundos), con el móvil nivelado, de modo que cada pared pase por el encuadre.
2. **Inclina arriba y abajo** una vez por pared: la unión con el techo y el zócalo con el
   suelo son lo que distingue una pared de un armario.
3. Ve a cada **esquina** y graba las dos paredes que se juntan desde 1,5 m.
4. Párate en cada **puerta** y graba hacia la habitación siguiente, luego pasa. El
   planificador marca un hueco como puerta solo si miró a través de él.
5. Ventanas: grábalas desde dentro, incluyendo la pared bajo y sobre ellas.
6. Repite en cada habitación. Sin prisa: **30–60 segundos por habitación**, nunca un
   barrido rápido.

## Qué no hacer

- No corras, no balancees el móvil, no camines girando rápido: desenfoque de movimiento.
- No grabes espejos, televisores ni paredes de cristal como si fueran paredes; no
  devuelven nada útil. levanta mostrará ese lado como «sin escanear» en vez de
  inventarlo.
- No cambies de lente ni hagas zoom a mitad del vídeo; la focal tiene que ser constante.
- No pares y vuelvas a grabar; un clip continuo por planta.
- No entregues un vídeo editado: los rótulos, fundidos y cortes se saltan (para un
  ordenador el texto sobre negro parece *más nítido* que cualquier habitación), pero cada
  corte rompe el solape entre fotogramas seguidos del que depende la reconstrucción. El
  clip en bruto siempre es mejor.

## Lo que enseñó el banco de pruebas

Medido en cinco habitaciones de ARKitScenes (paseos reales de iPhone con el suelo LiDAR
como verdad; [los números](../bench/results/arkitscenes_2026-09-05.md)):

- **Mide una puerta. Nada más arregla la escala.** La escala de la red quedó dentro del
  5 % en tres habitaciones, un 30 % corta en una y 4× desviada en un baño pequeño; darle
  la focal exacta cambió el resultado como mucho un 7 %, y no hacia la verdad. Hasta que
  pases `--door-width`, cada lámina lleva el sello PRELIMINAR a propósito.
- **Graba el suelo donde toca la pared, a lo largo de cada pared.** Las áreas salieron
  un 22–44 % por debajo del suelo LiDAR incluso con la escala bien: el contorno sigue
  el suelo que la cámara vio, y esos escaneos miraban objetos, no el zócalo. Recorre el
  perímetro con el móvil apuntando a la arista pared–suelo, no solo al centro.
- **Las habitaciones pequeñas son el peor caso.** Dos baños de 4–5 m² salieron un 31 %
  y un 78 % más grandes, uno con una sola pared. Ponte en el vano de la puerta, mantén
  1,5 m de distancia a lo que grabas, incluye el marco y el suelo, y cuenta con
  corregirlos a mano.
- **Una habitación, uno o dos minutos.** La trayectoria derivó 0,4–0,9 m en paseos de
  uno a tres minutos; todavía no hay cierre de bucle, así que deambular largo degrada
  el plano más de lo que lo haría un segundo clip corto.
- Las puertas se encuentran donde la cámara miró a través de ellas: en el banco estaban
  cerradas y levanta halló una en cinco. Abre las puertas antes de grabar.

## Comprueba antes de gastar GPU

```bash
levanta check recorrido.mp4
```

Informa de duración, resolución, nitidez y cuántos fotogramas aprovechables hay, con
avisos sobre los que puedes actuar. Después:

```bash
levanta video recorrido.mp4 -o out/casa --lang es --names "Sala,Cocina,Dormitorio,Baño"
```

## Escala

Desde vídeo a secas el tamaño puede salir un 5–15 % pequeño (ver las medidas del
README). Dos arreglos, el mejor primero:

- `--focal-px 1500` (o la focal en píxeles de tu móvil al tamaño de fotograma que usa
  levanta; los móviles a 1080p suelen estar entre 1400 y 1700 px). Permite a la red
  resolver la geometría con la focal fija.
- `--door-width 0.90` reescala el plano para que la puerta mediana detectada mida
  0,90 m. Mide una de tus puertas con un metro y pasa su ancho.

Los dos se pueden aplicar después con `levanta render plan.json --door-width 0.85`, sin
volver a reconstruir.
