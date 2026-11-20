"""Efeitos de estúdio: a MESMA definição usada na prévia do app (src/studio/filters.json).

- Cor: LUT 3D (.cube) em app/luts/ — o mesmo arquivo que a prévia do celular usa (assets/luts/).
  Os 5 LUTs são gerados por tools/luts.py; LUTs reais de cinema entram no mesmo lugar.
- Luz: vinheta (preto translúcido, como o app desenha por cima) e luz dividida do Neon (modo screen).
"""

from __future__ import annotations

import json
from pathlib import Path

FILTERS_PATH = Path(__file__).with_name('filters.json')
LUTS_DIR = Path(__file__).with_name('luts')


def load_filters() -> dict:
    with FILTERS_PATH.open(encoding='utf-8') as file:
        return json.load(file)


def filter_ids() -> list[str]:
    return list(load_filters()['order'])


def get_filter(filter_id: str) -> dict | None:
    return load_filters()['filters'].get(filter_id)


def lut_path(filter_def: dict) -> Path:
    """Arquivo .cube do efeito (o ffmpeg aplica com lut3d)."""
    return LUTS_DIR / filter_def['lut']


def _hex_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip('#')
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def vignette_alpha(x: float, y: float, strength: float) -> float:
    """Escurecimento (0..strength) no ponto (x, y) normalizado: nada no centro, máximo nos cantos.

    Igual ao RadialGradient do app: transparente até 55% do raio, `strength` no canto.
    """
    dx, dy = x - 0.5, y - 0.5
    distance = (dx * dx + dy * dy) ** 0.5 / (0.5 * 2**0.5)  # 0 no centro, 1 no canto
    if distance <= 0.55:
        return 0.0
    return strength * min(1.0, (distance - 0.55) / 0.45)


def split_color(x: float, split: dict) -> tuple[float, float, float]:
    """Luz dividida (já multiplicada pela força): cor da esquerda → nada no centro → cor da direita."""
    strength = float(split['strength'])
    if x < 0.5:
        color, weight = _hex_rgb(split['left']), (0.5 - x) / 0.5
    else:
        color, weight = _hex_rgb(split['right']), (x - 0.5) / 0.5
    k = strength * weight / 255.0
    return color[0] * k, color[1] * k, color[2] * k


def write_overlays(filter_def: dict, width: int, height: int, folder: Path) -> dict:
    """Gera as imagens de luz do filtro no tamanho final (numpy, rápido). Devolve os caminhos."""
    import numpy as np  # só no servidor (vem com o PyTorch)
    from PIL import Image

    created: dict[str, Path] = {}
    xs = np.linspace(0.0, 1.0, width)
    if filter_def.get('vignette'):
        strength = float(filter_def['vignette'])
        ys = np.linspace(0.0, 1.0, height)
        dx, dy = np.meshgrid(xs - 0.5, ys - 0.5)
        distance = np.sqrt(dx * dx + dy * dy) / (0.5 * 2**0.5)
        alpha = strength * np.clip((distance - 0.55) / 0.45, 0.0, 1.0)
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[..., 3] = np.round(alpha * 255).astype(np.uint8)
        created['vignette'] = folder / 'vignette.png'
        Image.fromarray(rgba, 'RGBA').save(created['vignette'])
    if filter_def.get('split'):
        row = np.array([split_color(x, filter_def['split']) for x in xs])
        rgb = np.round(np.tile(row[None, :, :], (height, 1, 1)) * 255).astype(np.uint8)
        created['split'] = folder / 'split.png'
        Image.fromarray(rgb, 'RGB').save(created['split'])
    return created
