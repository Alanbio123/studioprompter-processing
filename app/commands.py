"""Comandos do ffmpeg/ffprobe (funções puras: só montam a lista de argumentos)."""

from __future__ import annotations

from pathlib import Path

# Formatos: largura ÷ altura. 9:16 e 16:9 saem como foram gravados (sem recorte).
FORMAT_ASPECT = {'9:16': 9 / 16, '4:5': 4 / 5, '1:1': 1.0, '16:9': 16 / 9}
CROPPED_FORMATS = {'4:5', '1:1'}

# Voz realçada e volume nivelado (depois do DeepFilterNet), sempre em 48 kHz.
VOICE_CHAIN = ','.join(
    [
        'highpass=f=80',  # corta o grave de fundo (mesa, ar-condicionado)
        'equalizer=f=3000:t=q:w=1:g=2',  # presença da voz
        'acompressor=threshold=-20dB:ratio=3:attack=5:release=50',  # suaviza picos
        'loudnorm=I=-16:TP=-1.5:LRA=11',  # volume nivelado (padrão de redes sociais)
    ]
)

# Quanto ruído (dB), no máximo, o DeepFilterNet remove em cada modo (None = sem limite).
MODES = {'suave': 12.0, 'padrao': 24.0, 'forte': None}
DEFAULT_MODE = 'padrao'


def probe_command(source: Path) -> list[str]:
    return [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height:stream_side_data=rotation',
        '-of', 'json', str(source),
    ]


def display_size(probe: dict) -> tuple[int, int]:
    """Tamanho como o vídeo aparece (o iPhone grava deitado e marca a rotação)."""
    stream = probe['streams'][0]
    width, height = int(stream['width']), int(stream['height'])
    rotation = 0
    for side in stream.get('side_data_list', []) or []:
        if 'rotation' in side:
            rotation = int(side['rotation'])
    if abs(rotation) % 180 == 90:
        width, height = height, width
    return width, height


def crop_for(format_id: str, width: int, height: int) -> tuple[int, int] | None:
    """Recorte centralizado (largura, altura) para 4:5 e 1:1; None para os outros formatos."""
    if format_id not in CROPPED_FORMATS:
        return None
    aspect = FORMAT_ASPECT[format_id]
    if width / height > aspect:
        new_w, new_h = round(height * aspect), height
    else:
        new_w, new_h = width, round(width / aspect)
    return new_w - new_w % 2, new_h - new_h % 2  # H.264 pede medidas pares


def extract_audio_command(source: Path, wav: Path) -> list[str]:
    """Áudio do vídeo em mono 48 kHz (o que o DeepFilterNet usa)."""
    return ['ffmpeg', '-y', '-v', 'error', '-i', str(source), '-vn', '-ac', '1', '-ar', '48000',
            '-c:a', 'pcm_s16le', str(wav)]


def voice_command(denoised: Path, output: Path) -> list[str]:
    """Realce + nivelamento → AAC 48 kHz (o áudio limpo da prévia e do vídeo final)."""
    return ['ffmpeg', '-y', '-v', 'error', '-i', str(denoised), '-af', VOICE_CHAIN, '-ar', '48000',
            '-c:a', 'aac', '-b:a', '192k', str(output)]


def render_command(
    source: Path,
    output: Path,
    *,
    lut: Path,
    overlays: dict,
    crop: tuple[int, int] | None,
    sharpen: bool,
    audio: Path | None,
) -> list[str]:
    """Vídeo final: recorte → cor (LUT) → luz dividida (screen) → vinheta → nitidez; voz limpa."""
    inputs = ['-i', str(source)]
    next_input = 1
    chain = '[0:v]'
    steps = []
    if crop:
        steps.append(f'crop={crop[0]}:{crop[1]}')
    # Interpolação trilinear: a mesma do shader da prévia no app (prévia = vídeo final).
    steps.append(f"lut3d=file='{lut.as_posix()}':interp=trilinear")
    graph = [f"{chain}{','.join(steps)}[c0]"]
    current = 'c0'
    split = overlays.get('split')
    if split:
        inputs += ['-loop', '1', '-i', str(split)]
        graph.append(f'[{next_input}:v]format=gbrp[s]')
        graph.append(f'[{current}]format=gbrp[cg]')
        graph.append('[cg][s]blend=all_mode=screen:shortest=1[c1]')
        current = 'c1'
        next_input += 1
    vignette = overlays.get('vignette')
    if vignette:
        inputs += ['-loop', '1', '-i', str(vignette)]
        graph.append(f'[{current}][{next_input}:v]overlay=shortest=1:format=auto[c2]')
        current = 'c2'
        next_input += 1
    final = 'unsharp=5:5:0.8:5:5:0.0,format=yuv420p' if sharpen else 'format=yuv420p'
    graph.append(f'[{current}]{final}[v]')

    audio_map = ['-map', '0:a?']
    if audio:
        inputs += ['-i', str(audio)]
        audio_map = ['-map', f'{next_input}:a']

    return [
        'ffmpeg', '-y', '-v', 'error', '-progress', 'pipe:1', '-nostats',
        *inputs,
        # Poucas threads: cada thread do x264 guarda quadros 1080p (o Render grátis tem 512 MB).
        '-filter_complex_threads', '1',
        '-filter_complex', ';'.join(graph),
        '-map', '[v]', *audio_map,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
        '-threads', '2', '-x264-params', 'rc-lookahead=10',
        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        '-movflags', '+faststart', '-shortest',
        str(output),
    ]
