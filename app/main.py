"""Serviço de processamento do StudioPrompter (Hugging Face Space, Docker).

Toda rota exige `Authorization: Bearer <token>` assinado pelo Worker (o dono e o trabalho vêm no token).
Fluxo: PUT /jobs/upload → POST /jobs/clean → GET /jobs/status → GET /jobs/files/clean.m4a
→ POST /jobs/render → GET /jobs/files/final.mp4 (apaga tudo ao terminar de baixar).
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import commands, pipeline
from .filters import filter_ids
from .jobs import JobState, JobStore
from .tokens import verify

SECRET = os.environ.get('STUDIO_PROCESSING_SECRET', '')
MOCK = os.environ.get('PROCESSING_MOCK') == '1'
DATA_DIR = Path(os.environ.get('DATA_DIR', '/tmp/studioprompter'))
MAX_UPLOAD_BYTES = 400 * 1024 * 1024

app = FastAPI(title='StudioPrompter — processamento')
store = JobStore(DATA_DIR)
# Um trabalho pesado por vez: a CPU do plano grátis é pequena.
worker = ThreadPoolExecutor(max_workers=1)


def _expire_forever() -> None:
    while True:
        store.expire()
        time.sleep(300)


threading.Thread(target=_expire_forever, daemon=True).start()


def current_job(authorization: str = Header(default='')) -> JobState:
    token = authorization.removeprefix('Bearer ').strip()
    job = verify(SECRET, token)
    if job is None:
        raise HTTPException(status_code=401, detail='não autorizado')
    return store.get_or_create(job.job_id)


class CleanBody(BaseModel):
    mode: str = commands.DEFAULT_MODE


class RenderBody(BaseModel):
    filter: str
    format: str = '9:16'


@app.get('/')
def health() -> dict:
    return {'status': 'ok', 'mock': MOCK}


@app.put('/jobs/upload')
async def upload(request: Request, state: JobState = Depends(current_job)) -> dict:
    size = 0
    target = state.folder / pipeline.INPUT
    with target.open('wb') as file:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                file.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail='vídeo grande demais')
            file.write(chunk)
    if size == 0:
        raise HTTPException(status_code=400, detail='vídeo vazio')
    state.uploaded = True
    return state.public()


@app.post('/jobs/clean')
def clean(body: CleanBody, state: JobState = Depends(current_job)) -> dict:
    if body.mode not in commands.MODES:
        raise HTTPException(status_code=400, detail='modo inválido')
    if not state.uploaded:
        raise HTTPException(status_code=409, detail='envie o vídeo antes')
    if state.clean.status == 'processing' or state.render.status == 'processing':
        raise HTTPException(status_code=409, detail='processando')
    state.clean.status, state.clean.progress = 'processing', 0.0
    worker.submit(pipeline.clean_voice, state, body.mode, mock=MOCK)
    return state.public()


@app.get('/jobs/status')
def status(state: JobState = Depends(current_job)) -> dict:
    return state.public()


@app.post('/jobs/render')
def render(body: RenderBody, state: JobState = Depends(current_job)) -> dict:
    if body.filter not in filter_ids() or body.format not in commands.FORMAT_ASPECT:
        raise HTTPException(status_code=400, detail='filtro ou formato inválido')
    if not state.uploaded:
        raise HTTPException(status_code=409, detail='envie o vídeo antes')
    if state.clean.status == 'processing' or state.render.status == 'processing':
        raise HTTPException(status_code=409, detail='processando')
    state.render.status, state.render.progress = 'processing', 0.0
    worker.submit(pipeline.render_final, state, body.filter, body.format)
    return state.public()


@app.get('/jobs/files/clean.m4a')
def clean_file(state: JobState = Depends(current_job)) -> FileResponse:
    path = state.folder / pipeline.CLEAN_AUDIO
    if state.clean.status != 'done' or not path.exists():
        raise HTTPException(status_code=404, detail='ainda não está pronto')
    return FileResponse(path, media_type='audio/mp4')


@app.get('/jobs/files/final.mp4')
def final_file(tasks: BackgroundTasks, state: JobState = Depends(current_job)) -> FileResponse:
    path = state.folder / pipeline.FINAL
    if state.render.status != 'done' or not path.exists():
        raise HTTPException(status_code=404, detail='ainda não está pronto')
    # Privacidade: depois de enviar o vídeo final, apaga tudo deste trabalho.
    tasks.add_task(store.delete, state.job_id)
    return FileResponse(path, media_type='video/mp4', filename='studioprompter.mp4')


@app.delete('/jobs')
def discard(state: JobState = Depends(current_job)) -> dict:
    store.delete(state.job_id)
    return {'deleted': True}
