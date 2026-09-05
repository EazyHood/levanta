"""Labels printed on plans, drawings and the HTML viewer, in English and Spanish."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "room": "Room",
        "floor_plan": "Floor plan",
        "site_plan": "Site plan",
        "rooms": "rooms",
        "ceiling": "ceiling",
        "measured": "measured",
        "default": "default",
        "incomplete": "incomplete",
        "unscanned_side": "side not scanned",
        "door": "door",
        "window": "window",
        "passage": "passage",
        "building": "Building",
        "height": "h",
        "levels": "levels",
        "generated_by": "made with levanta",
        "total_area": "Total area",
        "plan_2d": "2D plan",
        "view_3d": "3D view",
        "measurements": "Measurements",
        "name": "Name",
        "area": "Area",
        "size": "Size",
        "status": "Status",
        "closed": "closed",
        "open": "open (a side was not scanned)",
        "openings": "Openings",
        "kind": "Type",
        "width": "Width",
        "bottom": "Bottom",
        "top": "Top",
        "walls": "walls",
        "walls_measured": "walls measured from both sides",
        "ceiling_height": "Ceiling height",
        "download_svg": "Download SVG",
        "download_glb": "Download 3D (GLB)",
        "no_3d": "The interactive 3D view needs an internet connection the first time (it loads a small viewer library). The drawing below never needs one.",
        "drag_hint": "Drag to orbit, scroll to zoom, right-drag to pan.",
        "scale_note": "Scale calibration",
        "site_limits": "From overhead data only footprint and height are known; nothing about walls or the interior.",
        "source": "Source",
        "footprint": "Footprint",
        "perimeter": "Perimeter",
    },
    "es": {
        "room": "Habitación",
        "floor_plan": "Plano de planta",
        "site_plan": "Plano de sitio",
        "rooms": "habitaciones",
        "ceiling": "techo",
        "measured": "medido",
        "default": "por defecto",
        "incomplete": "incompleta",
        "unscanned_side": "lado sin escanear",
        "door": "puerta",
        "window": "ventana",
        "passage": "paso",
        "building": "Edificio",
        "height": "h",
        "levels": "plantas",
        "generated_by": "hecho con levanta",
        "total_area": "Área total",
        "plan_2d": "Plano 2D",
        "view_3d": "Vista 3D",
        "measurements": "Medidas",
        "name": "Nombre",
        "area": "Área",
        "size": "Tamaño",
        "status": "Estado",
        "closed": "cerrada",
        "open": "abierta (un lado no se escaneó)",
        "openings": "Huecos",
        "kind": "Tipo",
        "width": "Ancho",
        "bottom": "Desde",
        "top": "Hasta",
        "walls": "paredes",
        "walls_measured": "paredes medidas por las dos caras",
        "ceiling_height": "Altura de techo",
        "download_svg": "Descargar SVG",
        "download_glb": "Descargar 3D (GLB)",
        "no_3d": "La vista 3D interactiva necesita internet la primera vez (carga una librería de visualización pequeña). El dibujo de abajo no lo necesita nunca.",
        "drag_hint": "Arrastra para girar, rueda para acercar, botón derecho para desplazar.",
        "scale_note": "Calibración de escala",
        "site_limits": "De los datos cenitales solo se conocen la huella y la altura; nada de paredes ni del interior.",
        "source": "Fuente",
        "footprint": "Huella",
        "perimeter": "Perímetro",
    },
}


def t(lang: str, key: str) -> str:
    table = STRINGS.get(lang, STRINGS["en"])
    return table.get(key, STRINGS["en"].get(key, key))


def fmt_len(v: float, units: str = "m") -> str:
    """3.20 m  |  10'6"  (feet and inches)."""
    if units == "ft":
        total_in = v / 0.0254
        ft = int(total_in // 12)
        inch = round(total_in - ft * 12)
        if inch == 12:
            ft, inch = ft + 1, 0
        return f"{ft}'{inch}\""
    return f"{v:.2f} m"


def fmt_area(v: float, units: str = "m") -> str:
    if units == "ft":
        return f"{v / 0.09290304:.0f} ft²"
    return f"{v:.2f} m²"
