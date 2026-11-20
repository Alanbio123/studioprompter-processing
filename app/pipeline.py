"""Processamento: limpar a voz (DeepFilterNet 3) e gerar o vídeo final (filtro + recorte + voz)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from . import commands
from .filters import get_filter, lut_path, write_overlays
from .jobs import JobState

INPUT = 'input.mp4'
RAW_AUDIO = 'raw.wav'
DENOISED = 'denoised.wav'
CLEAN_AUDIO = 'clean.m4a'
FINAL = 'final.mp4'

_model = None
log = logging.getLogger('uvicorn.error')


def _deepfilternet():
    """Carrega o modelo uma vez só (demora alguns segundos na 1ª limpeza)."""
    global _model
    if _model is None:
        from df.enhance import init_df

        model, df_state, _ = init_df()
        _model = (model, df_state)
    return _model


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:  # o fim do stderr do ffmpeg vai para o log com o erro
        raise RuntimeError(result.stderr.decode('utf-8', 'replace')[-800:])


def clean_voice(state: JobState, mode: str, *, mock: bool = False) -> None:
    """Áudio limpo em `clean.m4a`. `mock` pula o DeepFilterNet (testes sem o modelo)."""
    stage = state.clean
    stage.status, stage.progress, stage.detail = 'processing', 0.05, mode
    folder = state.folder
    try:
        _run(commands.extract_audio_command(folder / INPUT, folder / RAW_AUDIO))
        stage.progress = 0.2
        if mock:
            shutil.copyfile(folder / RAW_AUDIO, folder / DENOISED)
        else:
            from df.enhance import enhance, load_audio, save_audio

            model, df_state = _deepfilternet()
            audio, _ = load_audio(str(folder / RAW_AUDIO), sr=df_state.sr())
            limit = commands.MODES[mode]
            enhanced = enhance(model, df_state, audio, atten_lim_db=limit)
            save_audio(str(folder / DENOISED), enhanced, df_state.sr())
        stage.progress = 0.8
        _run(commands.voice_command(folder / DENOISED, folder / CLEAN_AUDIO))
        stage.status, stage.progress = 'done', 1.0
    except Exception:  # noqa: BLE001 — o app só precisa saber que falhou
        log.exception('limpeza da voz falhou')
        stage.status = 'failed'


def _duration_seconds(source: Path) -> float:
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(source)],
        check=True, capture_output=True, text=True,
    )
    return float(json.loads(result.stdout)['format']['duration'])


def render_final(state: JobState, filter_id: str, format_id: str) -> None:
    """Vídeo final em `final.mp4` com o filtro, o recorte (4:5/1:1) e a voz limpa (se houver)."""
    stage = state.render
    stage.status, stage.progress, stage.detail = 'processing', 0.02, f'{filter_id}:{format_id}'
    folder = state.folder
    try:
        filter_def = get_filter(filter_id)
        if filter_def is None:
            raise ValueError('filtro desconhecido')
        probe = subprocess.run(commands.probe_command(folder / INPUT), check=True,
                               capture_output=True, text=True)
        width, height = commands.display_size(json.loads(probe.stdout))
        crop = commands.crop_for(format_id, width, height)
        out_w, out_h = crop or (width, height)
        lut = lut_path(filter_def)
        overlays = write_overlays(filter_def, out_w, out_h, folder)
        clean = folder / CLEAN_AUDIO
        command = commands.render_command(
            folder / INPUT, folder / FINAL, lut=lut, overlays=overlays, crop=crop,
            sharpen=bool(filter_def.get('sharpen')),
            audio=clean if clean.exists() and state.clean.status == 'done' else None,
        )
        total = max(_duration_seconds(folder / INPUT), 0.1)
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                if line.startswith('out_time_us='):
                    try:
                        done = int(line.split('=', 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    stage.progress = min(0.98, max(stage.progress, done / total))
            if proc.wait() != 0:
                raise RuntimeError('ffmpeg falhou')
        stage.status, stage.progress = 'done', 1.0
    except Exception:  # noqa: BLE001
        log.exception('vídeo final falhou')
        stage.status = 'failed'
